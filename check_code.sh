#!/usr/bin/env bash
echo "Collecting python files..."
py_files=$(git ls-files -- '*.py')

if ! black -l 120 -S --check -q $py_files; \
then
  echo "'black' returned non-zero code"
  black -l 120 -S --diff -q $py_files
  exit 1
fi

if ! flake8 $py_files --max-line-length 1000; then
  echo "'flake8' returned non-zero code"
  exit 1
fi

echo "Nice."
