import string
import subprocess
import sys
import urllib.parse

valid_punctuation =  ' []()［］（）「」'

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

def is_link_text(text, left, right, pos1):
	if text.rfind(left, 0, pos1) <= text.rfind(right, 0, pos1):
		return False

	pos2 = text.find(right, pos1)

	if pos2 == -1:
		return False

	link_text = text[pos1:pos2]

	return len(link_text) == len(urllib.parse.quote(link_text, safe=':/'))

def fix_line_italics(line):
	pos1 = line.find('_')

	while pos1 != -1:
		if is_link_text(line, '[', ']', pos1):
			pos1 = line.find('_', line.find(']', pos1) + 1)
			continue

		if is_link_text(line, '(', ')', pos1):
			pos1 = line.find('_', line.find(')', pos1) + 1)
			continue

		pos2 = line.find('_', pos1+1)

		if pos2 == -1:
			return line

		# strip all the whitespace before/after the italic marker, then re-add
		# whatever whitespace is actually needed

		while pos1 > 0 and line[pos1-1].isspace():
			line = line[:pos1-1] + line[pos1:]
			pos1 = pos1 - 1
			pos2 = pos2 - 1

		while len(line) > pos1+1 and line[pos1+1].isspace():
			line = line[:pos1+1] + line[pos1+2:]
			pos2 = pos2 - 1

		if pos1 > 0 and not is_valid_next_to_italic(line[pos1-1]):
			line = line[:pos1] + ' ' + line[pos1:]
			pos1 = pos1 + 1
			pos2 = pos2 + 1

		# strip all the whitespace before/after the italic marker, then re-add
		# whatever whitespace is actually needed

		while line[pos2-1].isspace():
			line = line[:pos2-1] + line[pos2:]
			pos2 = pos2 - 1

		while len(line) > pos2+1 and line[pos2+1].isspace():
			line = line[:pos2+1] + line[pos2+2:]

		if len(line) > pos2+1 and not is_valid_next_to_italic(line[pos2+1]):
			line = line[:pos2+1] + ' ' + line[pos2+1:]
			pos2 = pos2 + 1

		pos1 = line.find('_', pos2 + 1)

	return line

def fix_italics(input_file):
	with open(input_file, 'r', encoding = 'utf-8') as f:
		input_lines = f.readlines()

	input_text = ''.join(input_lines)

	html = _pandoc(input_text, '--from', 'markdown', '--to', 'html')

	html = remove_tags(html, 'pre')
	html = remove_tags(html, 'code')

	text = _pandoc(html, '--from', 'html', '--to', 'plain', '--wrap=none')

	malformed_lines = [
		line for line in text.split('\n')
			if line.find('..') != 0 and line.find('_') != -1
	]

	if len(malformed_lines) == 0:
		return

	print(input_file)
	print('\n'.join(malformed_lines))

	fixed_lines = []

	in_code_block = False
	in_directive = False

	for line in input_text.split('\n'):
		if line.find('```') == 0:
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

		fixed_lines.append(fix_line_italics(line))

	output_text = '\n'.join(fixed_lines)

	if input_text == output_text:
		return

	with open(input_file, 'w', encoding = 'utf-8') as f:
		f.write(output_text)

for file in sys.argv[1:]:
	fix_italics(file)