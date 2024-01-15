# 🖱️ CopyQ Archive

A simple utility to archive CopyQ's history.

## Background

CopyQ can only store 10,000 items in its history.

This script can archive those items in a separate database. It comes with a CLI for querying the archive.

## Installation

1. Download the repository
2. `python3 -m pip install .`

## Usage

```bash
$ python3 -m copyq_archive [save|search|tabs]
```

### Save

```bash 
$ python3 -m copyq_archive save
```

### Search

```bash
$ python3 -m copyq_archive search "search-query"
``` 

#### Search tabs

```bash
$ python3 -m copyq_archive search tab "tab-name" "search-query"
```

### Tabs

```bash
$ python3 -m copyq_archive tabs
```
