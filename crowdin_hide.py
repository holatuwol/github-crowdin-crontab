from bs4 import BeautifulSoup
from crowdin_util import crowdin_http_request, crowdin_request, get_crowdin_file_info
import logging
import json
import os
import pandas as pd
from repository import CrowdInRepository, TranslationRepository
import sys

logging.basicConfig(
    format='%(asctime)s %(levelname)-8s %(message)s',
    level=logging.INFO,
    datefmt='%Y-%m-%d %H:%M:%S')

# Mass delete suggestions

def show_translation(repository, translation_id):
    crowdin_http_request(
        repository, '/backend/translation/change_visibility', 'GET',
        translation_id=translation_id, hidden=0)

def hide_translation(repository, translation_id):
    crowdin_http_request(
        repository, '/backend/translation/change_visibility', 'GET',
        translation_id=translation_id, hidden=1)

def process_phrases(repository, file_name, file_metadata, translation_filter, suggestion_filter):
    file_id = file_metadata['id']

    response_content = crowdin_http_request(
        repository, '/backend/phrases/phrases_as_html', 'GET',
        file_id=file_id)

    soup = BeautifulSoup(response_content, features='html.parser')

    translation_tags = [
        tag for tag in soup.find_all(attrs={'class': 'crowdin_phrase'})
    ]

    response_content = crowdin_http_request(
        repository, '/backend/phrases/load_preview', 'GET',
        file_id=file_id)

    response_data = json.loads(response_content.decode('utf-8'))['data']

    translations_hidden = {
        entry['id']: entry['hidden'] == '1'
            for entry in response_data
    }

    for tag in translation_tags:
        translation_id = tag.attrs['id'][len('crowdin_phrase_'):]

        is_hide_translation = translation_filter(tag)
        was_hidden_translation = translations_hidden[translation_id]

        if is_hide_translation == was_hidden_translation:
            continue

        if is_hide_translation:
            print('hide', tag)
            hide_translation(repository, translation_id)
        else:
            print('show', tag)
            show_translation(repository, translation_id)

    return False

# Clear out auto-translations so we have a better sense of progress

def delete_suggestions(repository, file_name, translation_id, suggestion_filter):
    response_content = crowdin_http_request(
        repository, '/backend/translation/phrase', 'GET',
        translation_id=translation_id)

    response_data = json.loads(response_content.decode('utf-8'))['data']

    if response_data['success']:
        raw_suggestions = response_data['suggestions']
    else:
        raw_suggestions = []

    if type(raw_suggestions) is dict:
        suggestions = [
            suggestion for key, sublist in raw_suggestions.items() for suggestion in sublist
                if suggestion_filter(suggestion)
        ]
    elif type(raw_suggestions) is list:
        suggestions = [
            suggestion for suggestion in raw_suggestions
                if suggestion_filter(suggestion)
        ]
    else:
        logging.info('Unable to find translation %s for file %s' % (translation_id, file_name))
        suggestions = []

    if len(suggestions) == 0:
        return False

    for suggestion in suggestions:
        logging.info('Deleting suggestion %s from user %s' % (suggestion['id'], suggestion['user']['login']))
        crowdin_http_request(
            repository, '/backend/suggestions/delete', 'GET',
            translation_id=translation_id, plural_id='-1', suggestion_id=suggestion['id'])

    return True

def delete_auto_translations(repository, file_info):
    for file_name, file_metadata in file_info.items():
        if 'id' not in file_metadata:
            continue

        logging.info('Removing auto-translations for file %s' % file_name)

        process_phrases(
            repository, file_name, file_metadata,
            lambda x: True,
            None,
            lambda x: x['user']['login'] == 'is-user')

# Tag checking against Crowdin HTML

def should_hide_tag(tag):
    if tag is None:
        return False

    if tag.name != 'code' and tag.name != 'pre':
        inner_html = tag.decode_contents()

        if inner_html[:5] == '<code' and inner_html[-7:] == '</code>':
        	return True
        
        if inner_html[:4] == '<pre' and inner_html[-5:] == '</pre>':
        	return True

        if inner_html[:4] == '<img' and inner_html[-2:] == '/>':
        	return True

        return False

    if 'class' not in tag.attrs:
        return True

    for x in tag.attrs['class']:
        if x is None or len(x) == 0:
            continue

        if x[-2:] == '::' or x[0] == '{':
            return False

    return True

def is_hidden_link(x):
    hidden_block = x.find_parent(attrs={'class': 'hidden_texts_block'})

    if hidden_block is None:
    	return False

    hidden_title = hidden_block.find(attrs={'class': 'hidden_phrases_title'})

    if hidden_title is None:
    	return False

    return hidden_title.text.strip() == 'Link addresses'

def is_within_code_tag(x):
    has_simple_match = x.text and x.text.find('[TOC') == 0 or \
        x.text and x.text.find('CVSS') != -1 and x.text.find('CVE') != -1 or \
        x.find_parent(attrs={'id': 'front-matter'}) is not None

    if has_simple_match:
        return True

    if should_hide_tag(x) or is_hidden_link(x):
        return True

    parent_code = x.find_parent('code')
    parent_pre = x.find_parent('pre')

    if parent_code is None and parent_pre is None:
        return False

    if parent_code is not None and not should_hide_tag(parent_code):
        return False

    if parent_pre is not None and not should_hide_tag(parent_pre):
        return False

    return True

def is_rst_directive(x):
    return x.text and ( \
        x.text.find('====') != -1 or x.text.find('----') != -1 or \
        x.text == '..' or x.text.find('::') != -1 or x.text.find(':') == 0 or \
        x.text.find(':doc:') != -1 or x.text.find(':ref:') != -1 or \
        x.text.lower() == x.text or \
        x.text[-3:] == '.md' or x.text[-4:] == '.rst' \
    )

# Clear out code translations

def hide_code_translations(repository, source_language, target_language, file_name, file_metadata):
    logging.info('Checking auto code translations for file %s' % file_name)

    if file_name[-4:] == '.rst':
        has_suggestions = process_phrases(
            repository, file_name, file_metadata,
            is_rst_directive, lambda x: True)
    else:
        has_suggestions = process_phrases(
            repository, file_name, file_metadata,
            is_within_code_tag, lambda x: x['user']['login'] == 'is-user')

    return has_suggestions

def process_code_translations(project_id, project_name, project_folder, source_language, target_language):
    status_code, response_text = crowdin_request(None, '/account/get-projects', 'GET', {'json': 'true'})

    projects = json.loads(response_text)['projects']

    project_api_keys = [project['key'] for project in projects if project['identifier'] == project_name]

    if len(project_api_keys) == 0:
        project_api_key = None
    else:
        project_api_key = project_api_keys[0]

    repository = TranslationRepository(None, CrowdInRepository(project_id, project_name, project_api_key, project_folder, False, False))

    file_info = get_crowdin_file_info(repository, target_language)

    for file_name, file_metadata in file_info.items():
        if 'id' in file_metadata and file_metadata['phrases'] != file_metadata['translated']:
            hide_code_translations(repository, source_language, target_language, file_name, file_metadata)

if __name__ == '__main__':
    process_code_translations(*sys.argv[1:])