import os
import sys

def process_open_tag_first(line, x):
	y = line.find('">', x)

	if y == -1:
		return line, False

	z = line.find('</a>', y)

	if z == -1:
		return line, False

	prefix = '[' if x == 0 or line[x-1] == ' ' else ' ['
	suffix = ')' if line[z+4] == ' ' else ') '

	return line[:x] + prefix + line[y+2:z].strip() + '](' + line[x+9:y] + suffix + line[z+4:], True

def process_close_tag_first(line, x):
	y = line.find('<a href="', x)

	if y == -1:
		return line, False

	z = line.find('">', y)

	if z == -1:
		return line, False

	prefix = '[' if x == 0 or line[x-1] == ' ' else ' ['
	suffix = ')' if line[z+2] == ' ' else ') '

	return line[:x] + prefix + line[x+4:y].strip() + '](' + line[y+9:z] + suffix + line[z+2:], True

def process_html_links(line):
	x = 0

	while True:
		x1 = line.find('<a href="', x)
		x2 = line.find('</a>', x)

		if x1 == -1 or x2 == -1:
			break

		if x1 < x2:
			line, is_continue = process_open_tag_first(line, x1)
			x = x1
		else:
			line, is_continue = process_close_tag_first(line, x2)
			x = x2

		if not is_continue:
			break

	return line

def process_markdown_file(file_name):
	if file_name[-3:] != '.md':
		return

	print('Processing ' + file_name)

	with open(file_name) as f:
		lines = f.readlines()

	fenced_block = None

	new_lines = []

	for line in lines:
		new_line = line

		stripped_line = new_line.strip()

		if fenced_block is not None and stripped_line == '</div></div>':
			fenced_block = None
			new_line = line[:line.find('</div>')] + '```'
		elif stripped_line[:26] == '<div class="adm-block adm-':
			fenced_block = stripped_line[26:stripped_line.find('"', 26)]
			print(fenced_block)
			new_line = line[:line.find('<div')] + '```{' + fenced_block + '}\n'
		else:
			new_line = process_html_links(line)

		new_lines.append(new_line)

	with open(file_name, 'w') as f:
		f.write(''.join(new_lines))

def process_file(argument_name):
	if os.path.isdir(argument_name):
		for root, dir_names, file_names in os.walk(argument_name):
			for file_name in file_names:
				process_markdown_file(os.path.join(root, file_name))
	else:
		process_markdown_file(argument_name)

if len(sys.argv) < 2:
	print('Please specify a folder or file to process')
else:
	for file_name in sys.argv[1:]:
		process_file(file_name)