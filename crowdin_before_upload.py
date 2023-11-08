import os
import sys

def process_md_links(line):
	x = 0

	while True:
		x = line.find('[', x)

		if x == -1:
			break

		y = line.find('](', x)

		if y == -1:
			break

		z = line.find(')', y)

		if z == -1:
			break

		if x > 0 and line[x-1] == '!':
			x = z + 1
			continue

		line = line[:x] + '<a href="' + line[y+2:z] + '">' + line[x+1:y] + '</a>' + line[z+1:]

	return line

def process_markdown_file(file_name):
	if file_name[-3:] != '.md':
		return

	print('Processing ' + file_name)

	with open(file_name) as f:
		lines = f.readlines()

	in_code_block = False
	fenced_block = None

	new_lines = []

	for line in lines:
		new_line = line

		stripped_line = new_line.strip()

		if stripped_line[:3] == '```':
			if in_code_block:
				in_code_block = False
			elif fenced_block is not None:
				if fenced_block != 'raw' and fenced_block != 'toctree':
					new_line = '</div></div>\n'
				fenced_block = None
			elif stripped_line[:4] == '```{' and stripped_line.find('}') != -1:
				fenced_block = stripped_line[4:stripped_line.find('}')]
				print(fenced_block)
				if fenced_block != 'raw' and fenced_block != 'toctree':
					new_line = line[:line.find('```')] + f'<div class="adm-block adm-{fenced_block}"><div class="adm-heading"><svg class="adm-icon"><use xlink:href="#adm-{fenced_block}"></use></svg><span>{fenced_block}</span></div><div class="adm-body">\n'
			else:
				in_code_block = True
		else:
			new_line = process_md_links(line)

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