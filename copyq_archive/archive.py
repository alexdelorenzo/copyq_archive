#!/usr/bin/env python
from __future__ import annotations

import asyncio
import logging
import sqlite3
from asyncio import to_thread
from datetime import datetime
from functools import partial
from pathlib import Path
from sqlite3 import Connection, Cursor
from subprocess import PIPE, Popen, run
from sys import argv
from typing import Final, IO, Iterable, NoReturn
from uuid import uuid4


log = logging.getLogger(f'{Path(__file__).name}')

CMD_NAME: Final[str] = 'copyq'
CMD_RUN_JS: Final[str] = f'{CMD_NAME} eval -'
CMD_GET_TABS: Final[str] = f'{CMD_NAME} tab'

RC_ERR: Final[int] = 1

DB_NAME: Final[str] = 'history.db'
DB_PATH: Final[Path] = (Path(__file__).parent / DB_NAME).absolute()

NO_ITEM: Final[str] = ''
NEW_LINE: Final[str] = '\n'

SEP_LINE: Final[str] = '-' * 5
SEP_QUERY: Final[str] = ' '

FMT_SEP_RECORD: Final[str] = f'{SEP_LINE} Item {{num}} from {{tab}} on {{time}} {SEP_LINE}{NEW_LINE}'
FMT_TIME: Final[str] = '%B %d, %Y @ %I:%M:%S %p'
FMT_QUERY: Final[str] = '%{query}%'

SENTINEL: Final[str] = str(uuid4())

SQL_WAL_MODE: Final[str] = 'pragma journal_mode=wal;'
SQL_CREATE_TBL: Final[str] = '''
CREATE TABLE IF NOT EXISTS items (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  tab TEXT DEFAULT 'default',
  content TEXT,
  first FLOAT,
  last FLOAT
);

CREATE INDEX IF NOT EXISTS tab_idx ON items(tab);
'''

SQL_FIND_CONTENT: Final[str] = '''
SELECT
  id
FROM
  items
WHERE
  content=? AND tab=?
'''

SQL_SEARCH_QUERY: Final[str] = '''
SELECT 
  tab, content, last
FROM 
  items
WHERE 
  content like ?
ORDER BY 
  last DESC
'''

SQL_SEARCH_TAB: Final[str] = f'''
SELECT 
  tab, content, last
FROM 
  items
WHERE 
  content like ? AND tab=?
ORDER BY 
  last DESC
'''

SQL_INSERT_ITEM: Final[str] = '''
INSERT INTO 
  items(tab, content, first, last)
VALUES 
  (?, ?, ?, ?)
'''

SQL_UPDATE_LAST_SEEN: Final[str] = '''
UPDATE 
  items
SET 
  tab=?, last=?
WHERE 
  id=?
'''

SQL_COUNT_ITEMS: Final[str] = '''
SELECT 
  COUNT(DISTINCT content)
FROM
  items
'''

FMT_JS_GET_ITEMS: Final[str] = '''
const MIME = 'text/plain';
const SEP = '\\n';
const START = 1;

tab('{tab}');

let item;
const tabSize = size() + START;

for (let itemNum = tabSize; itemNum > START; --itemNum) {{
  let record = read(MIME, itemNum);

  if (item = str(record)) {{
    print('{sentinel}' + SEP);
    print(item + SEP);
  }}
}}

'''

COUNT_DEFAULT: Final[int] = 0
COUNT_START: Final[int] = 1


type Items = Iterable[str]


def get_tab_js(tab: str) -> str:
  return FMT_JS_GET_ITEMS.format(tab=tab, sentinel=SENTINEL)


def get_tabs() -> list[str]:
  process = run(CMD_GET_TABS, shell=True, capture_output=True, text=True)
  tabs = process.stdout.strip(NEW_LINE).split(NEW_LINE)

  return sorted(tabs)


async def run_backup(tabs: list[str] = None):
  tabs = tabs or get_tabs()
  coros = map(backup, tabs)

  await asyncio.gather(*coros)


def backup_tab(tab: str) -> int | NoReturn:
  try:
    process = Popen(CMD_RUN_JS, shell=True, stdin=PIPE, stdout=PIPE, text=True)
    pipe_js(process.stdin, tab)

  except Exception as e:
    log.exception(e)
    quit(RC_ERR)

  if process.stderr:
    log.error(process.stderr)
    quit(RC_ERR)

  items: Items = gen_items(process.stdout)
  save_items(items, tab)

  return process.wait()


backup = partial(to_thread, backup_tab)


def pipe_js(stdin: IO, tab: str):
  js: str = get_tab_js(tab)
  stdin.write(js)
  stdin.flush()
  stdin.close()


def gen_items(stdout: IO) -> Items:
  item: str = NO_ITEM

  for line in stdout:
    if line.startswith(SENTINEL):
      if item:
        yield item.strip(NEW_LINE)
        item = NO_ITEM

      continue

    item = f'{item}{line}{NEW_LINE}'

  if item:
    yield item.strip(NEW_LINE)


def save_items(items: Items, tab: str):
  connection, cursor = get_db()
  time: float = datetime.now().timestamp()
  count: int = COUNT_DEFAULT

  with connection:
    for count, item in enumerate(items, start=COUNT_START):
      save_item(cursor, item, tab, time)

  log.info(f'Saved {count} items in {tab}.')


def save_item(cursor: Cursor, item: str, tab: str, time: float):
  params: tuple[str, str] = item, tab
  cursor.execute(SQL_FIND_CONTENT, params)

  match cursor.fetchone():
    case row_id, *_:
      row: tuple[str, float, int] = tab, time, row_id
      cursor.execute(SQL_UPDATE_LAST_SEEN, row)

    case [] | None:
      row: tuple[str, str, float, float] = tab, item, time, time
      cursor.execute(SQL_INSERT_ITEM, row)


def get_db() -> tuple[Connection, Cursor]:
  connection = sqlite3.connect(DB_PATH)
  cursor = connection.cursor()

  cursor.execute(SQL_WAL_MODE)
  cursor.executescript(SQL_CREATE_TBL)

  return connection, cursor


async def search(query: str, tab: str | None = None):
  if not DB_PATH.exists():
    log.warning('Must load clipboards into database file first, might take some time.')
    await run_backup()

  _, cursor = get_db()
  regex: str = FMT_QUERY.format(query=query)

  if tab:
    params: tuple[str, str] = regex, tab
    cursor.execute(SQL_SEARCH_TAB, params)

  else:
    params: tuple[str] = regex,
    cursor.execute(SQL_SEARCH_QUERY, params)

  count: int = COUNT_DEFAULT
  items = cursor.fetchall()

  for count, (tab, content, time) in enumerate(items, start=COUNT_START):
    item = get_formatted_item(tab, content, time, count)
    print(item)

  cursor.execute(SQL_COUNT_ITEMS)
  [total] = cursor.fetchone()

  log.info(f'Found {count} items out of {total} total items.')


def get_sep(tab: str, time: float, count: int) -> str:
  time: str = datetime.fromtimestamp(time).strftime(FMT_TIME)

  return FMT_SEP_RECORD.format(num=count, tab=tab, time=time)


def get_formatted_item(tab: str, content: str, time: float, count: int) -> str:
  sep = get_sep(tab, time, count)

  return f'{sep}{content}{NEW_LINE}'


async def main():
  args: list[str]
  _, *args = argv

  match args:
    case ['save'] | []:
      await run_backup()

    case 'save', *tabs:
      await run_backup(tabs)

    case ['tabs']:
      tabs: list[str] = get_tabs()
      print(NEW_LINE.join(tabs))

    case 'search', 'tab', tab, *query:
      query: str = SEP_QUERY.join(query)
      await search(query, tab)

    case 'search', *query:
      query: str = SEP_QUERY.join(query)
      await search(query)

    case _:
      log.error('Please use search, save or tabs commands.')
      quit(RC_ERR)


def run_sync():
  logging.basicConfig(level=logging.DEBUG)

  coro = main()
  asyncio.run(coro)


if __name__ == '__main__':
  run_sync()
