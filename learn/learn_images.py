import os
import git
from glob import glob
from learn_util import *
import re

def is_missing_image(image_file, image_path, content):
	if os.path.exists(image_path) or os.path.exists(image_path.replace('/en/', '/ja/')):
		return False

	image_pos = content.find(image_file)
	comment_begin = content.rfind('<!--', 0, image_pos)
	comment_end = content.rfind('-->', 0, image_pos)

	if comment_begin > comment_end:
		return False

	return True

def check_images(ja_file):
	with open(ja_file, encoding='utf-8', mode = 'r') as f:
		content = ''.join(f.readlines())

	image_files = re.findall(r'\!\[[^\]]+\]\(([^\) ]+)[^\)]*\)', content)

	if len(image_files) == 0:
		return

	en_folder = os.path.dirname(ja_file).replace('/ja/', '/en/')

	image_paths = [
		(image_file, resolve_path(en_folder, image_file))
			for image_file in image_files
	]

	missing_images = [
		(image_file, image_path) for image_file, image_path in image_paths
			if is_missing_image(image_file, image_path, content)
	]

	if len(missing_images) == 0:
		return

	for image_file, en_image_path in missing_images:
		ja_image_path = en_image_path.replace('/en/', '/ja/')

		git_hash = git.log('-1', '--pretty=%H', '--', en_image_path)

		if git_hash is None or len(git_hash) == 0:
			en_image_path = en_image_path.replace('/latest/', '/7.x/')
			git_hash = git.log('-1', '--pretty=%H', '--', en_image_path)

		if git_hash is None  or len(git_hash) == 0:
			continue

		git.checkout('%s~1' % git_hash, '--', en_image_path)

		if not os.path.exists(en_image_path):
			continue

		os.makedirs(os.path.dirname(ja_image_path), exist_ok=True)
		os.rename(en_image_path, ja_image_path)

	missing_images = [
		(image_file, image_path) for image_file, image_path in image_paths
			if is_missing_image(image_file, image_path, content)
	]

	if len(missing_images) == 0:
		return

	print('subl %s' % ja_file)

	en_file = get_en_file(ja_file)

	if os.path.exists(en_file):
		print('subl %s' % en_file)

	print('\n'.join([
		' * %s => %s' % (image_file, image_path)
			for image_file, image_path in missing_images
	]))
	print()

for root_dir, folders, ja_files in os.walk(os.getcwd()):
	for ja_file in ja_files:
		if ja_file[-3:] == '.md':
			check_images(os.path.join(root_dir, ja_file))
