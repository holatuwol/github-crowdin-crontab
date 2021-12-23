import os

def resolve_path(folder, file):
	while file[0] == '.':
		while file[:2] == './':
			file = file[2:]

		while file[:3] == '../':
			folder = os.path.dirname(folder)
			file = file[3:]

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