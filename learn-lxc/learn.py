from bs4 import BeautifulSoup
import datetime
import inspect
import json
import os
import re
import requests
import sys
import zipfile

script_root_folder = os.path.dirname(os.path.dirname(os.path.abspath(inspect.getfile(inspect.currentframe()))))
faster_deploy_folder = os.path.join(os.path.dirname(script_root_folder), 'liferay-faster-deploy')

sys.path.insert(0, script_root_folder)
sys.path.insert(0, faster_deploy_folder)

from cronjob import get_repositories
from crowdin import crowdin_download_translations, crowdin_upload_sources, pre_translate
from crowdin_sync import get_repository_state, update_repository
import git
import onepass
from patcher.scrape_liferay import authenticate, get_full_url, get_liferay_content, make_liferay_request, progress_bar_request, session




# domain = 'localhost:8080'
# base_url = 'http://%s' % domain
# group_id = '20117'
# class_name_id = '29337'
# base_folder = '/home/me/dev/compose/sandbox/test'
# test_article_id = None

domain = 'learn-uat.liferay.com'
base_url = 'https://%s' % domain
group_id = '32483059'
class_name_id = '20132'
base_folder = '/home/me/dev/projects/learn-xliff'
test_article_id = '33226688'

access_token = None
access_token_expires = None

headers = {
	'User-Agent': 'scrape_liferay.py'
}

def authorize():
	global access_token, access_token_expires

	if access_token is not None and datetime.datetime.now() < access_token_expires:
		return

	client_id = onepass.item('OAuth2 %s' % domain, 'username')['username']
	client_secret = onepass.item('OAuth2 %s' % domain, 'credential')['credential']

	params = {
		'client_id': client_id,
		'client_secret': client_secret,
		'grant_type': 'client_credentials'
	}

	r = session.post(f'{base_url}/o/oauth2/token', data=params, headers=headers)
	response_json = r.json()

	access_token = response_json['access_token']
	access_token_expires = datetime.datetime.now() + datetime.timedelta(seconds = response_json['expires_in'])

	headers['Authorization'] = f'Bearer {access_token}'

def merge_items(old_items, new_items):
	new_ids = set([item['id'] for item in new_items])

	merged_items = [item for item in old_items if item['id'] not in new_ids]
	merged_items.extend(new_items)

	return merged_items

def make_headless_get_request(url, initial_params):
	params = initial_params.copy()

	params['page'] = 1
	params['pageSize'] = 100
	params['sort'] = 'dateModified'

	authorize()
	r = session.get(url, params=params, headers=headers)

	response_json = r.json()
	items = response_json['items']
	page_number = 1

	while len(items) < response_json['totalCount']:
		page_number = page_number + 1

		params['page'] = page_number
		print(f'{url} ({(page_number - 1) * 100} of {response_json["totalCount"]} results already seen)')

		authorize()
		r = session.get(url, params=params, headers=headers)

		response_json = r.json()
		items.extend(response_json['items'])

		params['page'] = page_number

	return items

def get_articles_last_modified(update=True):
	old_articles_last_modified = []
	min_modified_date = '1970-01-01T00:00:00Z'

	articles_last_modified_file = '%s/articles_last_modified.json' % base_folder

	if os.path.exists(articles_last_modified_file):
		with open(articles_last_modified_file, 'r') as f:
			old_articles_last_modified = json.load(f)

	if len(old_articles_last_modified) > 0:
		min_modified_date = max([article['dateModified'] for article in old_articles_last_modified])

	if not update:
		return old_articles_last_modified

	get_articles_url = f'{base_url}/o/headless-delivery/v1.0/sites/{group_id}/structured-contents'

	params = {
		'flatten': 'true',
		'fields': 'id,dateModified',
		'filter': f'dateModified ge {min_modified_date}'
	}

	new_articles_last_modified = make_headless_get_request(get_articles_url, params)
	print(len(new_articles_last_modified), 'articles modified since', min_modified_date)

	merged_articles_last_modified = merge_items(old_articles_last_modified, new_articles_last_modified)

	with open(articles_last_modified_file, 'w') as f:
		json.dump(merged_articles_last_modified, f)

	return merged_articles_last_modified

def export_old_translation(article_id, article_modified, source_language, target_language):
	xliff_file = f'{base_folder}/{article_id}.xliff'
	zip_file = f'{base_folder}/{article_id}.zip'

	if os.path.exists(xliff_file):
		xliff_modified = datetime.datetime.fromtimestamp(os.path.getmtime(xliff_file))

		if article_modified == xliff_modified:
			return xliff_file

	print('Exporting old translation for %s' % xliff_file)

	export_url = f'{base_url}/o/translation/export_translation'

	params = {
		'classNameId': str(class_name_id),
		'classPK': str(article_id),
		'groupId': str(group_id),
		'exportMimeType': 'application/xliff+xml',
		'sourceLanguageId': source_language,
		'targetLanguageIds': target_language
	}

	r = make_liferay_request(export_url, params=params)

	if r.status_code != 200:
		return None

	with open(zip_file, 'wb') as f:
		progress_bar_request(r, f)

	with zipfile.ZipFile(zip_file, 'r') as f:
		xliff_data = f.read(f.namelist()[0])

		with open(xliff_file, 'wb') as f:
			f.write(xliff_data)

	os.utime(xliff_file, (article_modified.timestamp(), article_modified.timestamp()))

	# os.remove(zip_file)

	return xliff_file

translation_form_token = None
translation_resource_token = None

def get_translation_auth_token(article_id):
	global translation_form_token
	global translation_resource_token

	if translation_form_token is not None and translation_resource_token is not None:
		return translation_form_token, translation_resource_token

	params = {
		'p_p_id': 'com_liferay_translation_web_internal_portlet_TranslationPortlet',
		'_com_liferay_translation_web_internal_portlet_TranslationPortlet_mvcRenderCommandName': '/translation/import_translation',
		'_com_liferay_translation_web_internal_portlet_TranslationPortlet_classNameId': class_name_id,
		'_com_liferay_translation_web_internal_portlet_TranslationPortlet_classPK': article_id,
		'_com_liferay_translation_web_internal_portlet_TranslationPortlet_groupId': group_id,
		'_com_liferay_translation_web_internal_portlet_TranslationPortlet_portletResource': 'com_liferay_journal_web_portlet_JournalPortlet',
		'p_p_state': 'pop_up'
	}

	r = make_liferay_request(f'{base_url}/group/guest/~/control_panel/manage', params, allow_redirects=False)
	print(r)

	response_text = r.text

	translation_form_token = re.compile("Liferay.authToken = '[A-Za-z0-9]*'").findall(response_text)[0].split("'")[1]
	translation_resource_token = re.compile('p_p_auth=[A-Za-z0-9]*').findall(response_text)[0].split('=')[1]
	return translation_form_token, translation_resource_token

def import_new_translation(article_id):
	form_token, resource_token = get_translation_auth_token(article_id)

	xliff_file = f'{base_folder}/{article_id}.xliff'

	params = {
		'p_p_id': 'com_liferay_translation_web_internal_portlet_TranslationPortlet',
		'p_p_lifecycle': '1',
		'p_p_state': 'maximized',
		'p_p_mode': 'view',
		'_com_liferay_translation_web_internal_portlet_TranslationPortlet_javax.portlet.action': '/translation/import_translation',
		'_com_liferay_translation_web_internal_portlet_TranslationPortlet_classNameId': class_name_id,
		'_com_liferay_translation_web_internal_portlet_TranslationPortlet_classPK': article_id,
		'_com_liferay_translation_web_internal_portlet_TranslationPortlet_groupId': group_id,
		'_com_liferay_translation_web_internal_portlet_TranslationPortlet_title': article_id,
		'_com_liferay_translation_web_internal_portlet_TranslationPortlet_portletResource': 'com_liferay_journal_web_portlet_JournalPortlet',
		'_com_liferay_translation_web_internal_portlet_TranslationPortlet_workflowAction': '1',
		'p_p_auth': resource_token,
		'p_auth': form_token,
	}

	files = {
		'_com_liferay_translation_web_internal_portlet_TranslationPortlet_file': (f'{article_id}.xliff', open(xliff_file, 'rb')),
	}

	r = make_liferay_request(f'{base_url}/group/guest/~/control_panel/manage', params=params, multipart_params=files, method='post', allow_redirects=False)
	print(r)

def extract_source_content(article, source_language, target_language):
	article_id = article['id']
	article_modified = datetime.datetime.strptime(article['dateModified'], '%Y-%m-%dT%H:%M:%SZ')

	source_html_file = f'{base_folder}/{source_language[:2]}/{article_id}.html'
	target_html_file = f'{base_folder}/{target_language[:2]}/{article_id}.html'

	xliff_file = export_old_translation(article_id, article_modified, source_language, target_language)

	if xliff_file is None:
		return None

	if os.path.exists(target_html_file):
		target_html_modified = datetime.datetime.fromtimestamp(os.path.getmtime(target_html_file))

		if article_modified == target_html_modified:
			return None

	with open(xliff_file, 'r') as f:
		soup = BeautifulSoup(f, 'xml')

	content = soup.find(id='DDMStructure_content')

	if content is None:
		return None

	source_content = '<html><body>' + content.segment.source.get_text() + '</body></html>'

	if os.path.exists(source_html_file):
		with open(source_html_file, 'r') as f:
			old_content = f.read()

		if source_content == old_content:
			return None

	with open(source_html_file, 'w') as f:
		f.write(source_content)

	os.utime(source_html_file, (article_modified.timestamp(), article_modified.timestamp()))

	return source_html_file

def publish_target_content(article_id, target_language, target_html_file):
	with open(target_html_file, 'r') as f:
		new_target_content = f.read()[len('<html><body>'):-len('</body></html>')]

	xliff_file = f'{base_folder}/{article_id}.xliff'

	with open(xliff_file, 'r') as f:
		soup = BeautifulSoup(f, 'xml')

	content = soup.find(id='DDMStructure_content')

	old_target_content = content.segment.target.get_text()

	if new_target_content == old_target_content:
		print('Translation for article', article_id, 'has not changed')
		return

	content.segment.target.string = new_target_content

	with open(xliff_file, 'wb') as f:
		f.write(soup.encode('UTF-8'))

	print('Importing new translation for article', article_id, 'from', xliff_file)
	import_new_translation(article_id)

def copy_learn_to_crowdin(source_language, target_language):
	all_repositories = get_repositories()
	repository = [x for x in all_repositories if x.crowdin.dest_folder == 'learn.liferay.com'][0]

	updated_articles = [
		x[len(base_folder):] for x in [
			extract_source_content(article, source_language, target_language)
				for article in get_articles_last_modified()
		] if x is not None
	]

	if domain.find('localhost') != -1:
		return

	if test_article_id is not None:
		test_article_file_name = 'en/%s.html' % test_article_id
		updated_articles = [x for x in updated_articles if x == test_article_file_name]

	if not updated_articles:
		return

	old_dir = os.getcwd()
	os.chdir(base_folder)

	crowdin_upload_sources(repository, source_language[:2], target_language[:2], updated_articles)

	os.chdir(old_dir)

def translate_learn_on_crowdin(source_language, target_language):
	all_repositories = get_repositories()
	repository = [x for x in all_repositories if x.crowdin.dest_folder == 'learn.liferay.com'][0]

	new_files, all_files, file_info = get_repository_state(repository, source_language[:2], target_language[:2])

	updated_articles = [
		x[len(base_folder):] for x in [
			extract_source_content(article, source_language, target_language)
				for article in get_articles_last_modified()
		] if x is not None
	]

	if test_article_id is not None:
		test_article_file_name = 'en/%s.html' % test_article_id
		updated_articles = [x for x in updated_articles if x == test_article_file_name]

	if not updated_articles:
		return

	old_dir = os.getcwd()
	os.chdir(base_folder)

	pre_translate(repository, source_language[:2], target_language[:2], updated_articles, file_info)

	crowdin_download_translations(repository, source_language[:2], target_language[:2], updated_articles, file_info)

	os.chdir(old_dir)

def copy_crowdin_to_learn(source_language, target_language):
	old_dir = os.getcwd()
	os.chdir(base_folder)

	for html_file in os.listdir(target_language[:2]):
		article_id = html_file[:html_file.rfind('.')]
		publish_target_content(article_id, target_language, f'{target_language[:2]}/{html_file}')

	os.chdir(old_dir)

if __name__ == '__main__':
	if domain.find('localhost') != -1:
		authenticate('%s/c/portal/login' % base_url)
	else:
		authenticate('%s/group/control_panel' % base_url)

	copy_learn_to_crowdin('en_US', 'ja_JP')
	translate_learn_on_crowdin('en_US', 'ja_JP')
	copy_crowdin_to_learn('en_US', 'ja_JP')