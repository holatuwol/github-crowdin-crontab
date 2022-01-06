import os
from glob import glob
from learn_util import *
import re

def is_broken_link(link_file, link_path, content):
	if os.path.exists(link_path):
		return False

	if link_path[-5:] == '.html':
		if os.path.exists(link_path[:-5] + '.rst') or os.path.exists(link_path[:-5] + '.md'):
			return False

	link_pos = content.find(link_file)
	comment_begin = content.rfind('<!--', 0, link_pos)
	comment_end = content.rfind('-->', 0, link_pos)

	if comment_begin > comment_end:
		return False

	return True

def is_checkable_link(link):
	extension = link[link.rfind('.'):]

	if extension in ['.gif', '.jpeg', '.jpg', '.png']:
		return False

	if link[:4] == 'http' or link[:4] == 'TODO':
		return False

	if link.find('#') != -1:
		return False

	return True

def get_links(file):
	if not os.path.exists(file):
		return '', []

	with open(file, encoding='utf-8', mode = 'r') as f:
		content = ''.join(f.readlines())

	return content, [
		link for link in re.findall(r'\[[^\]]+\]\(([^\) ]+)[^\)]*\)', content)
			if is_checkable_link(link)
	]

def get_broken_links(file, link_files, content):
	if len(link_files) == 0:
		return []

	folder = os.path.dirname(file)

	link_paths = [
		(link_file, resolve_path(folder, link_file)) for link_file in link_files
	]

	return [
		link_file for link_file, link_path in link_paths
			if is_broken_link(link_file, link_path, content)
	]

def fix_links(file, en_link_files, ja_link_files, missing_link_files):
	with open(file, encoding='utf-8', mode = 'r') as f:
		ja_content = ''.join(f.readlines())

	if len(en_link_files) == len(ja_link_files):
		new_ja_content = []

		for en_link, ja_link in zip(en_link_files, ja_link_files):
			if ja_link not in missing_link_files:
				continue

			pos = ja_content.find(ja_link)

			new_ja_content.append(ja_content[:pos])
			new_ja_content.append(en_link)

			ja_content = ja_content[pos+len(ja_link):]

		new_ja_content.append(ja_content)

		ja_content = ''.join(new_ja_content)

	new_ja_content = ja_content

	en_link_files = set(en_link_files)

	for ja_link in set(missing_link_files):
		matching_basenames = get_basename_files(file, ja_link)

		if len(matching_basenames) != 1:
			continue

		new_ja_content = new_ja_content.replace(ja_link, matching_basenames[0])

	with open(file, 'w', encoding = 'utf-8') as f:
		f.write(new_ja_content)

def check_links(ja_file):
	en_file = get_en_file(ja_file)

	ja_content, ja_link_files = get_links(ja_file)
	ja_missing_link_files = get_broken_links(ja_file, ja_link_files, ja_content)

	if len(ja_missing_link_files) == 0:
		return

	en_content, en_link_files = get_links(en_file)

	fix_links(ja_file, en_link_files, ja_link_files, ja_missing_link_files)

	ja_content, ja_link_files = get_links(ja_file)
	ja_missing_link_files = get_broken_links(ja_file, ja_link_files, ja_content)

	if len(ja_missing_link_files) == 0:
		return

	if len(ja_missing_link_files) == 0:
		return

	print('subl %s' % ja_file)

	if os.path.exists(en_file):
		print('subl %s' % en_file)

	print('\n'.join([
		' * %s => %s' % (link_file, resolve_path(os.path.dirname(ja_file), link_file))
			for link_file in ja_missing_link_files
	]))
	print()

for root_dir, folders, files in os.walk(os.getcwd()):
	for file in files:
		if file[-3:] == '.md':
			check_links(os.path.join(root_dir, file))
