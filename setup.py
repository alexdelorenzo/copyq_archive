from setuptools import setup, find_packages

setup(
  name='copyq_archive',
  version='0.0.1',
  description='Archive CopyQ items to a SQLite database',
  author='Alex DeLorenzo <alex@alexdelorenzo.dev',
  packages=find_packages(),
  zip_safe=True,
  python_requires='>=3.12',
)
