import string
import subprocess
import sys
import urllib.parse

valid_punctuation =  '* []()［］（）「」'

def _pandoc(input_text, *args):
    cmd = ['pandoc'] + list(args)

    pipe = subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    out, err = pipe.communicate(input=input_text.encode('UTF-8'))

    return out.decode('UTF-8', 'replace')

def remove_tags(text, tag):
  open_tag = '<%s' % tag
  close_tag = '</%s>' % tag

  pos1 = text.find(open_tag)
  while pos1 != -1:
    pos2 = text.find(close_tag, pos1)
    text = text[0:pos1] + text[pos2+len(close_tag):]
    pos1 = text.find(open_tag)

  return text

def is_valid_next_to_italic(ch):
	return ch.isspace() or ch in valid_punctuation

def is_link_text(text, left, right, start):
	pos1 = text.rfind(left, 0, start)

	if pos1 <= text.rfind(right, 0, start):
		return False

	pos1 = pos1 + 1
	pos2 = text.find(right, pos1)

	if pos2 == -1:
		return False

	link_text = text[pos1:pos2]

	if link_text[0] == '%' and link_text[-1] == '%':
		return True

	if link_text[0] == '$' and link_text[-1] == '$':
		return True

	return len(link_text) == len(urllib.parse.quote(link_text, safe=':/?=#'))

def fix_line_italics(line, marker):
	pos1 = 0

	line_prefix = ''
	leading_space = -1
	leading_marker = -1

	if marker[0] == '*':
		for i, ch in enumerate(line):
			if ch == marker[0]:
				leading_marker = i
			elif ch.isspace():
				if leading_marker == -1:
					leading_space = i
			else:
				break

	if marker == '*':
		if leading_space < leading_marker:
			if line[leading_marker+1].isspace():
				line_prefix = line[:leading_marker+2]
				line = line[leading_marker+2:]
			else:
				line_prefix = line[:leading_space+1]
				line = line[leading_space+1:]
		elif leading_space > -1:
			line_prefix = line[:leading_space+1]
			line = line[leading_space+1:]
	elif leading_space > -1:
		line_prefix = line[:leading_space+1]
		line = line[leading_space+1:]

	pos1 = line.find(marker, pos1)

	while pos1 != -1:
		backtick_count = len([ch for ch in line[:pos1] if ch == '`'])

		if backtick_count % 2 == 1:
			pos2 = line.find('`', pos1)

			if pos2 != -1:
				pos1 = line.find(marker, pos2)
				continue

		if is_link_text(line, '[', ']', pos1):
			pos1 = line.find(marker, line.find(']', pos1) + 1)
			continue

		if is_link_text(line, '(', ')', pos1):
			pos1 = line.find(marker, line.find(')', pos1) + 1)
			continue

		if marker == '*' and line[pos1+1] == '*':
			pos2 = line.find('**', pos1+2)

			if pos2 == -1:
				return line_prefix + line

			pos1 = line.find(marker, pos2+2)
			continue

		pos2 = line.find(marker, pos1+len(marker))

		if pos2 == -1:
			return line_prefix + line

		# strip all the whitespace before/after the italic marker, then re-add
		# whatever whitespace is actually needed

		while pos1 > 0 and line[pos1-1].isspace():
			line = line[:pos1-1] + line[pos1:]
			pos1 = pos1 - 1
			pos2 = pos2 - 1

		while pos1+len(marker)+1 < len(line) and line[pos1+len(marker)].isspace():
			line = line[:pos1+len(marker)] + line[pos1+len(marker)+1:]
			pos2 = pos2 - 1

		if pos1 > 0 and not is_valid_next_to_italic(line[pos1-1]):
			line = line[:pos1] + ' ' + line[pos1:]
			pos1 = pos1 + 1
			pos2 = pos2 + 1

		if pos1+len(marker)+1 < len(line) and line[pos1+len(marker)] in valid_punctuation:
			line = line[:pos1] + line[pos1+len(marker)] + marker + line[pos1+len(marker)+1:]
			pos1 = pos1 + 1

		if marker != '**' and line[pos1+1] != '*':
			line = line[:pos1] + '**' + line[pos1+1:]
			pos1 = pos1 + 1
			pos2 = pos2 + 1

		# strip all the whitespace before/after the italic marker, then re-add
		# whatever whitespace is actually needed

		while line[pos2-1].isspace():
			line = line[:pos2-1] + line[pos2:]
			pos2 = pos2 - 1

		while pos2+len(marker)+1 < len(line) and line[pos2+len(marker)].isspace():
			line = line[:pos2+len(marker)] + line[pos2+len(marker)+1:]

		if pos2+len(marker)+1 < len(line) and not is_valid_next_to_italic(line[pos2+len(marker)]):
			line = line[:pos2+len(marker)] + ' ' + line[pos2+len(marker):]

		if pos2 > 0 and line[pos2-1] in valid_punctuation:
			line = line[:pos2-1] + marker + line[pos2-1] + line[pos2+len(marker):]
			pos2 = pos2 - 1

		if marker != '**' and line[pos2+1] != '*':
			line = line[:pos2] + '**' + line[pos2+1:]
			pos2 = pos2 + 1

		pos1 = line.find(marker, pos2 + 1)

	return line_prefix + line

def extract_text(input_text):
	html = _pandoc(input_text, '--from', 'markdown', '--to', 'html')

	html = remove_tags(html, 'pre')
	html = remove_tags(html, 'code')

	return _pandoc(html, '--from', 'html', '--to', 'plain', '--wrap=none')

def fix_italics(input_file):
	with open(input_file, 'r', encoding = 'utf-8') as f:
		input_lines = f.readlines()

	fixed_lines = []
	malformed_lines = []

	in_code_block = False
	in_directive = False

	for line in input_lines:
		if line.strip().find('```') == 0:
			in_code_block = not in_code_block
			fixed_lines.append(line)
			continue

		if in_code_block:
			fixed_lines.append(line)
			continue

		if line.find('..') == 0:
			in_directive = True
			fixed_lines.append(line)
			continue

		if in_directive:
			if len(line.strip()) == 0:
				fixed_lines.append(line)
				continue

			if line[0].isspace():
				fixed_lines.append(line)
				continue

			in_directive = False

		fixed_line = line
		fixed_line = fix_line_italics(fixed_line, '_')
		fixed_line = fix_line_italics(fixed_line, '*')
		fixed_line = fix_line_italics(fixed_line, '**')

		if fixed_line != line:
			malformed_lines.append(line)

		fixed_lines.append(fixed_line)

	if len(malformed_lines) == 0:
		return

#	print(input_file)
#	print(''.join(malformed_lines))

	with open(input_file, 'w', encoding = 'utf-8') as f:
		f.write(''.join(fixed_lines))

files = []

if len(sys.argv) == 1:
	files = git.ls_files('*.md').split('\n')
else:
	files = sys.argv[1:]

for file in files:
	fix_italics(file)