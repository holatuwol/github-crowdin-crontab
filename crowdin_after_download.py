import os
import sys

def process_html_links(line):
	x = 0

	while True:
		x = line.find('<a href="', x)

		if x == -1:
			break

		y = line.find('">', x)

		if y == -1:
			break

		z = line.find('</a>', y)

		if z == -1:
			break

		line = line[:x] + '[' + line[y+2:z] + '](' + line[x+9:y] + ') ' + line[z+4:]

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