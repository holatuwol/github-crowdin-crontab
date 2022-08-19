from inspect import getsourcefile
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(getsourcefile(lambda:0)))), 'zendesk'))

from zendesk import get_zendesk_article, zendesk_get_request

cached_titles = {}

def get_help_center_title(request_url, language_id):
	key = request_url + '::' + language_id

	if key in cached_titles:
		return cached_titles[key]

	if request_url.find('https://help.liferay.com/hc/') != 0:
		return None, None

	if request_url.find('#') != -1:
		request_url = request_url[:request_url.find('#')]

	if request_url.find('?') != -1:
		request_url = request_url[:request_url.find('?')]

	pos0 = request_url.rfind('/') + 1
	pos1 = request_url.find('-', pos0)

	if pos1 == -1:
		pos1 = len(request_url)

	if request_url.find('/articles/') != -1:
		article_id = request_url[pos0:pos1]
		article = get_zendesk_article('help.liferay.com', article_id, language_id)

		if article is None:
			cached_titles[key] = (None, None)
		else:
			cached_titles[key] = (article['html_url'], '%s (ヘルプセンター)' % article['title'])
	elif request_url.find('/sections/') != -1:
		section_id = request_url[pos0:pos1]

		translations = zendesk_get_request('help.liferay.com', '/help_center/sections/%s/translations/%s.json' % (section_id, language_id), 'translation')

		if len(translations) == 0:
			cached_titles[key] = (None, None)
		else:
			cached_titles[key] = (translations[0]['html_url'], translations[0]['title'])
	else:
		cached_titles[key] = (None, None)

	return cached_titles[key]

def resolve_path(folder, file):
	while folder[-1] == '/':
		folder = folder[:-1]

	while file[0] == '.':
		for i, ch in enumerate(file):
			if ch == '/':
				break
			elif ch != '.':
				return os.path.join(folder, file)

		if i > 1:
			folder = os.path.dirname(folder)

		file = file[i+1:]

	return os.path.join(folder, file)

def get_exact_file(source_file, target_file, relativize):
	rst_name = target_file[:target_file.rfind('.')] + '.rst'

	if os.path.exists(rst_name):
		return rst_name if relativize else resolve_path(os.path.dirname(source_file), rst_name)

	rst_name = target_file[:target_file.rfind('.')].replace('-', '_') + '.rst'

	if os.path.exists(rst_name):
		return rst_name if relativize else resolve_path(os.path.dirname(source_file), rst_name)

	md_name = target_file[:target_file.rfind('.')].replace('_', '-') + '.md'

	if os.path.exists(md_name):
		return md_name if relativize else resolve_path(os.path.dirname(source_file), md_name)

	return None

def get_basename_files(source_file, target_file, relativize=True):
	if source_file.find('/en/') == -1 and source_file.find('/ja/') == -1:
		return []

	if target_file.find('/en/') == -1 and target_file.find('/ja/') == -1:
		return []

	if os.path.exists(target_file):
		return [target_file if relativize else resolve_path(os.getcwd(), target_file)]

	matching_basenames = []

	if target_file[-3:] == '.md' or target_file[-5:] == '.html':
		exact_match = get_exact_file(source_file, target_file, relativize)

		if exact_match is not None:
			return [exact_match]

	if source_file[0] != '/':
		source_file = resolve_path(os.getcwd(), source_file)

	basename = os.path.basename(target_file)
	base_dir = os.path.dirname(source_file)

	while os.path.basename(base_dir) != 'ja' and os.path.basename(base_dir) != 'en':
		base_dir = os.path.dirname(base_dir)

		if base_dir == '/':
			print(source_file, target_file)

	for root_dir, folders, files in os.walk(base_dir):
		for file in files:
			if basename == os.path.basename(file):
				file_path = os.path.join(root_dir, file)

				if relativize:
					file_path = os.path.relpath(file_path, start=os.path.dirname(source_file))

				matching_basenames.append(file_path)

	if len(matching_basenames) != 0:
		return matching_basenames

	if target_file[-3:] == '.md' or target_file[-5:] == '.html':
		rst_basename = target_file[:target_file.rfind('.')] + '.rst'
		matching_basenames = get_basename_files(source_file, rst_basename, relativize)

		if len(matching_basenames) != 0:
			return matching_basenames

		rst_basename = target_file[:target_file.rfind('.')].replace('-', '_') + '.rst'
		matching_basenames = get_basename_files(source_file, rst_basename, relativize)

		if len(matching_basenames) != 0:
			return matching_basenames

	return []

def get_en_file(ja_file):
	en_file = ja_file.replace('/ja/', '/en/')

	if os.path.exists(en_file):
		return en_file

	basename_files = get_basename_files(en_file, os.path.basename(en_file), False)

	if len(basename_files) == 1:
		return basename_files[0]

	en_file = ja_file.replace('/ja/', '/en/').replace('-dxp', '')

	if os.path.exists(en_file):
		return en_file

	basename_files = get_basename_files(en_file, os.path.basename(en_file), False)

	if len(basename_files) == 1:
		return basename_files[0]

	en_file = ja_file.replace('/ja/', '/en/').replace('-liferay-dxp', '')

	if os.path.exists(en_file):
		return en_file

	basename_files = get_basename_files(en_file, os.path.basename(en_file), False)

	if len(basename_files) == 1:
		return basename_files[0]

	return ja_file.replace('/ja/', '/en/')


def get_full_title(file_path, title, content):
	if file_path.find('/en/') != -1:
		if content.find('Coming Soon!') != -1:
			return title + ' (Coming Soon!)'

		readme_path = file_path[:file_path.rfind('.')] + '/README.rst'

		if content.find(readme_path) != -1:
			return extract_title_from_rst(readme_path)

		return title

	if file_path.find('/ja/') != -1:
		if content.find('近日公開！') != -1:
			return title + ' (近日公開！)'

		readme_path = file_path[:file_path.rfind('.')] + '/README.rst'

		if content.find(readme_path) != -1:
			return extract_title_from_rst(readme_path)

		return title

	return title

def extract_title_from_md(file_path):
	with open(file_path, encoding='utf-8', mode = 'r') as f:
		lines = f.readlines()

	title = None

	for line in lines:
		if line.find('#') == 0 and line.find(' ') != -1:
			title = line[line.find(' ')+1:].strip()
			break

	if title is None:
		return None

	content = ''.join(lines)

	return get_full_title(file_path, title, content)

def extract_title_from_rst(file_path):
	with open(file_path, encoding='utf-8', mode = 'r') as f:
		lines = f.readlines()

	title = None

	for line in lines:
		if len(line.strip()) != 0:
			title = line.strip()
			break

	if title is None:
		return None

	content = ''.join(lines)

	return get_full_title(file_path, title, content)
