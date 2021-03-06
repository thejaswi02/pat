#!/usr/bin/env python3
# Dedicated to the public domain under CC0: https://creativecommons.org/publicdomain/zero/1.0/.

import re
import sys

from subprocess import run, PIPE
from argparse import ArgumentParser, FileType
from collections import defaultdict
from difflib import SequenceMatcher
from pithy.io import failF
from pithy.seq import group_seq_by_heads, HeadlessMode


__all__ = ['pat_dependencies', 'main']


pat_version = '0'


def main():
  # I cannot get argparse to do quite what I want, so using two parsers for now.
  parser = ArgumentParser(prog='pat', description='create or apply a .pat patch file.')
  parser.epilog = "for help with a specific command, pass '-h' to that command."

  subs = parser.add_subparsers()
  subs.required = True # unofficial workaround.
  subs.dest = 'command' # this is necessary to make `required` above work.

  sub_gitdiff = subs.add_parser('gitdiff',
    help='create .pat style diff between two existing source files.')

  sub_gitdiff.set_defaults(handler=main_diff)

  sub_gitdiff.add_argument('original', type=FileType('r'),
    help='source file to use as the basis (left/minus side) of the patch.')

  sub_gitdiff.add_argument('modified', type=FileType('r'),
    help='source file to use as the modification (right/plus side) from which to calculate the patch.')

  sub_gitdiff.add_argument('destination', nargs='?', type=FileType('w'), default='-',
    help='output path (defaults to stdout)')

  sub_gitdiff.add_argument('-min-context', type=int, default=3,
    help='minimum number of lines of context to show before each hunk.')

  sub_diff = subs.add_parser('gitdiff',
    help='create .pat style diff between two existing source files.')

  sub_diff.set_defaults(handler=main_gitdiff)

  sub_diff.add_argument('original', type=FileType('r'),
    help='source file to use as the basis (left/minus side) of the patch.')

  sub_diff.add_argument('modified', type=FileType('r'),
    help='source file to use as the modification (right/plus side) from which to calculate the patch.')

  sub_diff.add_argument('destination', nargs='?', type=FileType('w'), default='-',
    help='output path (defaults to stdout)')

  sub_diff.add_argument('-min-context', type=int, default=3,
    help='minimum number of lines of context to show before each hunk.')

  sub_apply = subs.add_parser('apply',
    help='apply a .pat patch file to an existing, matching source file.')

  sub_apply.set_defaults(handler=main_apply)

  sub_apply.add_argument('patch', type=FileType('r'),
    help='input .pat path to apply')

  sub_apply.add_argument('destination', nargs='?', type=FileType('w'), default='-',
    help='output path (defaults to stdout)')

  args = parser.parse_args()
  args.handler(args)

def get_matches(s, hunk_start, hunk_end, origLines):
  matches=[]
  s.set_seq1(origLines[hunk_start:hunk_end])
  for match in s.get_matching_blocks():
    i, j, n = match
    if (n == hunk_end - hunk_start):
      matches.append(match)
  return matches

# Inefficient, change to add up indices of multiple matching blocks when they overlap
def get_hunk_context(s, hunk_start, hunk_end, origLines):
  #print("Hunk Start", hunk_start)
  #print("Hunk End", hunk_end)
  #Check first time if the hunk is unique 
  matches=get_matches(s, hunk_start, hunk_end, origLines)
  while len(matches) > 1:
    if hunk_start > 0:
      hunk_start = hunk_start - 1
    else:
      return hunk_start, hunk_end
    matches=get_matches(s, hunk_start, hunk_end, origLines)
  return hunk_start, hunk_end

def main_gitdiff(args):
  original = args.original
  modified = args.modified
  f_out = args.destination
  min_context = args.min_context

  if original.name.find('..') != -1:
    failF("original path cannot contain '..': {!r}", original.name)

  origLines = original.readlines()

  s = SequenceMatcher(None)
  s.set_seq2(origLines)

  out = sys.stdout # get the buffer.
  cmd = 'git diff --exit-code --no-index --no-color --histogram --unified=0'.split() 
  cmd.append(original.name)
  cmd.append(modified.name)
  sub = run(cmd, stdout=PIPE, universal_newlines=True)
  if sub.returncode not in (0, 1):
    failF('pat: git diff failed with status code: {}.', sub.returncode)
  out.write('pat v0\n')

  groups = group_seq_by_heads(seq=sub.stdout.splitlines(True),
    is_head=lambda line: line.startswith('@@'),
    headless=HeadlessMode.drop)

  # print("Number of groups",len(groups))
  for group in groups:
    # out.write('Group\n')
    head = group[0]
    a = re.search('-.*\+', str(head)).group(0)
    # out.write('Start line: ')

    # Array index starts with 0 git diff is with 1
    start_line_num = a[1:a.find(',')]
    # out.write(start_line_num.encode('ascii') + '\n'.encode('ascii'))
    start_line_num = int(a[1:a.find(',')])

    # Special case when start line number from git diff is 0. Its always a line added in the begining
    if(start_line_num == 0):
      hunk_start = start_line_num
      hunk_end = start_line_num
    else:
      start_line_num = start_line_num - 1
      hunk_start = start_line_num - min_context
      if hunk_start < 0:
        hunk_start = 0
      hunk_end = start_line_num

      #out.write("Hunk Start"), hunk_start)
      #print("Hunk End", hunk_end)
      hunk_start, hunk_end = get_hunk_context(s, hunk_start, hunk_end, origLines) 

    if hunk_start == 0:
      out.write('|^\n')
    for line in origLines[hunk_start:hunk_end]:
      out.write('| ')
      out.write(line)
      
    for line in group[1:]:
      if line.startswith('-'):
        out.write('- ')
        out.write(line[1:])
      elif line.startswith('+'):
        out.write('+ ')
        out.write(line[1:])
      else:
        failF('invalid line in diff output: {!r}', line)

def main_diff(args):
  'diff command entry point.'
  original = args.original
  modified = args.modified
  f_out = args.destination
  min_context = args.min_context

  if min_context < 1: failF('min-context value must be positive.')

  if original.name.find('..') != -1:
    failF("original path cannot contain '..': {!r}", original.name)

  o_lines = original.readlines()
  m_lines = modified.readlines()

  if o_lines and not o_lines[-1].endswith('\n'):
    failF('{}:{} original document is missing final newline (not yet supported).')
  if m_lines and not m_lines[-1].endswith('\n'):
    failF('{}:{} modified document is missing final newline (not yet supported).')

  def write(line): f_out.write(line)

  write('pat v' + pat_version + '\n')

  orig_path_clean = args.original.name
  if orig_path_clean.startswith('_build/'):
    orig_path_clean = orig_path_clean[len('_build/'):]
  write(orig_path_clean + '\n')

  line_indices = defaultdict(set) # maps line contents to line numbers.
  for i, line in enumerate(o_lines):
    line_indices[line].add(i)

  matches = diff_lines(o_lines, m_lines)
  # returns triples of form (i, j, n); o_lines[i:i+n] == m_lines[j:j+n].
  # matches are monotonically increasing in i and j.
  # the last match is a sentinal with (len(o_lines), len(m_lines), 0).
  # it is the only match with n == 0.
  # for non-sentinel adjacent matches (i, j, n) and (i1, j1, n1),
  # then i+n != i1 or j+n != j1, or both.
  # in other words, adjacent matches always describe non-adjacent equal blocks.

  # conceptually, we turn the sequence of matches into a sequence of hunks,
  # where each hunk is a pair of (match, diff).
  # however actually materializing the diff is not necessary;
  # we simply get the match at the start, or synthesize an empty one as appropriate.
  has_start_symbol = False
  i, j, n = matches[0]
  match_iter = iter(matches)
  if i == 0 and j == 0: # real match at start.
    if n == len(o_lines) and n == len(m_lines): # o and m are identical.
      return # avoids outputting a trailing newline.
    next(match_iter) # advance.
  else: # need a dummy match to start the first hunk.
    i, j, n = (0, 0, 0)

  for i1, j1, n1 in match_iter:
    di = i + n # beginning of diff for o.
    dj = j + n # beginning of diff for m.
    if di == len(o_lines) and dj == len(m_lines): break # no diff.
    # calculate how much context we need for this hunk to be ambiguous.
    # this includes the lines subtracted from the original in the calculation.
    # start with the last deleted line of the current diff in o.
    ci = i1 - 1
    matching_indices = line_indices[o_lines[ci]] if (ci >= 0) else set()
    # iterate back through the first line of context.
    #errFL('\ni:{}-{}-{} j:{}-{}-{} ci:{} mi:{}', i, di, i1, j, dj, j1, ci, matching_indices)
    for ci in range(ci - 1, i - 1, -1):
      decr_indices = { j - 1 for j in matching_indices } # step all candidates backwards.
      curr_indices = line_indices[o_lines[ci]]
      matching_indices = decr_indices.intersection(curr_indices)
      #errFL('  ci: {}; decr:{} curr:{} mi:{}', ci, decr_indices, curr_indices, matching_indices)
      if len(matching_indices) == 1:
        break
    ci = max(i, min(ci, di - min_context))
    #errFL('* ci:{}', ci)
    if ci == 0 and not has_start_symbol:
      has_start_symbol = True
      write('\n|^\n') # add first separator line and start-of-file symbol line.
    elif i < ci: # not merged with previous hunk; separate with blank line.
      write('\n')
    # output context and diff.
    for o in range(ci, di):
      write('| ' + o_lines[o]) # write context lines.
    for o in range(di, i1):
      write('- ' + o_lines[o]) # remove lines from original.
    for m in range(dj, j1):
      write('+ ' + m_lines[m]) # add lines from modified.
    i = i1
    j = j1
    n = n1


def diff_lines(o_lines, m_lines):
  return SequenceMatcher(None, o_lines, m_lines).get_matching_blocks()


def open_orig_path(path):
  try:
   return open(path)
  except FileNotFoundError:
    pass
  if not path.startswith('/') and not path.startswith('_build/'):
    build_path = '_build/' + path
    try:
      return open(build_path)
    except FileNotFoundError:
      patch_failF(1, 'could not open source path specified by patch: {!r}\n'
        '  also could not open corresponding build path: {!r}', path, build_path)
  else:
    patch_failF(1, 'could not open source path specified by patch: {!r}', path)


# version pattern is applied to the first line of documents;
# programs processing input strings may or may not check for a version as appropriate.
version_re = re.compile(r'pat v(\d+)\n')

def main_apply(args):
  'apply command entry point.'
  f_patch = args.patch
  f_out = args.destination

  def patch_failF(startline_num, fmt, *items):
    failF('{}:{}: ' + fmt, f_patch.name, start_line_num + 1, *items)

  version_line = f_patch.readline()
  orig_line = f_patch.readline()
  patch_lines = f_patch.readlines()

  m = version_re.fullmatch(version_line)
  if not m:
    patch_failF(0, 'first line should specify pat version matching pattern: {!r}\n  found: {!r}',
      version_re.pattern, version_line)
  version = m.group(1)
  if version != pat_version: patch_failF(0, 'unsupported version number: {}', version)

  if not orig_line:
    patch_failF(1, 'patch file does not specify an original path')
  orig_path = orig_line.rstrip()

  if orig_path.find('..') != -1:
    patch_failF(1, "original path cannot contain '..': {!r}", orig_path)

  f_orig = open_orig_path(orig_path)

  orig_lines = f_orig.readlines()

  orig_line_indices = defaultdict(set)
  for i, orig_line in enumerate(orig_lines):
    orig_line_indices[orig_line].add(i)

  len_orig = len(orig_lines)
  orig_index = 0
  def orig_line(): return orig_lines[orig_index]

  for pi, patch_line in enumerate(patch_lines, 2): # advance two lines.
    if patch_line == '\n':
      continue
    if patch_line == '|^\n':
      if orig_index != 0:
        patch_failF(pi, 'patch start-of-file symbol `|^` may only occur at beginning of patch.')
      continue
    prefix = patch_line[0]
    line = patch_line[2:]
    if prefix == '#':
      pass
    elif prefix in '|-':
      orig_index_start = orig_index
      while orig_index < len_orig and orig_line() != line:
        f_out.write(orig_line())
        orig_index += 1
      if orig_index == len_orig:
        patch_failF(pi, 'patch context line does not match in source line range: {}-{}\n{}',
          orig_index_start + 1, orig_index + 1, patch_line)
      if prefix == '|':
        f_out.write(orig_line())
      orig_index += 1
    elif prefix == '+':
      f_out.write(line)
    else:
      patch_failF(pi, 'bad patch line prefix: {!r}',  prefix)

  while orig_index < len_orig:
    f_out.write(orig_line())
    orig_index += 1


def pat_dependencies(src_path, src_file, dir_names):
  '''
  Return a list of dependencies;
  `dir_names` is an ignored parameter provided by muck.
  A .pat file always has a single dependency: the source file it patches.
  '''
  version_line = src_file.readline()
  orig_line = src_file.readline()
  orig_path = orig_line.strip()
  if not orig_path:
    failF('pat_dependencies: {}:2: line specifying original path is missing or empty.', src_path)
  return [orig_path]


def errF(fmt, *items):
  print(fmt.format(*items), end='', file=sys.stderr)

def errFL(fmt, *items):
  print(fmt.format(*items), file=sys.stderr)

def failF(fmt, *items):
  errFL('pat error: ' + fmt, *items)
  sys.exit(1)


if __name__ == '__main__': main()
