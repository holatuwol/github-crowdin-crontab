#!/usr/bin/env python

import codecs
import os
import sys

ignore_characters = '∟→↑←↓⇨▼○×‘⌘├──'
japanese_spaces = '\u3000\u00a0'
japanese_punctuation = '【】「」（）：…⋮・□。、'

def get_previous_tag(utf8_string, pos):
	y = utf8_string.rfind('>', 0, pos)

	if y == -1:
		return None

	x = utf8_string.rfind('<', 0, y)

	if x == -1:
		return None

	tag = utf8_string[x+1:y]

	if tag == 'br':
		return get_previous_tag(utf8_string, x)

	return tag

def requires_new_english_translation(utf8_string):
	for ch in japanese_spaces:
		if utf8_string.find(ch) != -1:
			return True

	for i, ch in enumerate(utf8_string):
		if ord(ch) > 127 and ch not in ignore_characters and ch not in japanese_punctuation:
			tag = get_previous_tag(utf8_string, i)
			if tag != 'code' and tag != 'pre':
				return True

	return False

def prepare_japanese_for_translation(utf8_string):
	new_utf8_sb = []

	for i, old_ch in enumerate(utf8_string):
		if old_ch == '<' or old_ch == '<':
			tag = get_previous_tag(utf8_string, i)
			if tag != 'code' and tag != 'pre':
				new_ch = '\n' + old_ch
			else:
				new_ch = old_ch
		elif ord(old_ch) <= 127:
			new_ch = old_ch
		elif old_ch in japanese_spaces:
			new_ch = ' '
		else:
			new_ch = old_ch

		new_utf8_sb.append(new_ch)

	return ''.join(new_utf8_sb)

def retranslate_ja_to_en():
	article_paths = {}

	for subdir, dirs, en_files in os.walk('en/'):
		for en_file in en_files:
			en_file_path = os.path.join(subdir, en_file)
			ja_file_path = 'ja/' + en_file_path[3:]

			if not os.path.exists(ja_file_path):
				continue

			with codecs.open(en_file_path, 'r', 'utf-8') as f:
				en_content = f.read()

			if not requires_new_english_translation(en_content):
				continue

			x = ja_file_path.rfind('/')
			y = ja_file_path.find('-', x)

			article_paths[ja_file_path[x+1:y]] = ja_file_path

			with codecs.open(ja_file_path, 'r', 'utf-8') as f:
				ja_content = prepare_japanese_for_translation(f.read())

			with codecs.open(ja_file_path, 'w', 'utf-8') as f:
				f.write(ja_content)
				print(ja_file_path)

	return article_paths