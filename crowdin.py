from bs4 import BeautifulSoup
from collections import defaultdict
import git
from file_manager import get_local_file, get_crowdin_file, get_root_folders
import json
import logging
import os
import pandas as pd
from repository import initial_dir
import requests
from scrape_liferay import authenticate, session
from subprocess import Popen, PIPE

def _crowdin(*args, stderr=PIPE):
    cmd = ['crowdin'] + list(args)

    logging.info(' '.join(cmd))

    pipe = Popen(cmd, stdout=PIPE, stderr=stderr)
    out, err = pipe.communicate()

    return out.decode('UTF-8', 'replace').strip()

# Use "pandoc" to disable word wrapping to improve machine translations.

def _pandoc(filename, *args):
    with open(filename, 'r') as f:
        lines = f.readlines()

        title_pos = -1
        toc_pos = -1

        for i, line in enumerate(lines):
            if title_pos == -1 and line.find('#') == 0:
                title_pos = i
            elif line.find('[TOC') == 0:
                toc_pos = i

        head_lines = ''.join(lines[0:max(title_pos, toc_pos)+1])
        tail_lines = ''.join(lines[max(title_pos, toc_pos)+1:])

    cmd = ['pandoc'] + list(args)

    pipe = Popen(cmd, stdin=PIPE, stdout=PIPE, stderr=PIPE)
    out, err = pipe.communicate(input=tail_lines.encode('UTF-8'))

    nowrap_lines = out.decode('UTF-8', 'replace')

    with open(filename, 'w') as f:
        f.write(head_lines)
        f.write('\n')
        f.write(nowrap_lines)

# Generate a "crowdin.yaml" file to tell the CLI what to do.

def get_crowdin_config_entry(repository, file):
    assert(not os.path.isdir(file))

    if file[0:3] == 'en/':
        translation = '%two_letters_code%/' + file[3:]
    else:
        translation = file.replace('/en/', '/%two_letters_code%/')

    dest = '/' + get_crowdin_file(repository, file)

    return {
        'source': file,
        'dest': dest,
        'translation': translation
    }

def configure_crowdin(repository, files):
    configs = [get_crowdin_config_entry(repository, file) for file in files]
    config_json = json.dumps(configs, indent=2)

    with open('%s/crowdin.yaml' % repository.github.git_root, 'w') as f:
        f.write('''
"project_identifier" : "{crowdin_project_name}"
"api_key" : "{crowdin_api_key}"
"base_path" : "{git_root}"
"preserve_hierarchy": true

"files": {files}
'''.format(
        crowdin_project_name=repository.crowdin.project_name,
        crowdin_api_key=repository.crowdin.api_key,
        git_root=repository.github.git_root,
        files=config_json
    ))

# Wrapper functions to upload sources and download translations.

def crowdin_upload_sources(repository, new_files):
    before_upload = get_crowdin_file_info(repository)

    for file in new_files:
        extension = file[file.rfind('.'):]

        if extension == '.md' or extension == '.markdown':
            _pandoc(file, '--from=gfm', '--to=gfm', '--wrap=none')

            with open(file, 'r') as f:
                file_content = f.read()

            file_content = file_content.replace('@<', '@').replace('@>', '@')

            with open(file, 'w') as f:
                f.write(file_content)

    if len(new_files) > 0:
        configure_crowdin(repository, new_files)
        _crowdin('upload', 'sources')

    git.reset('--hard')

    after_upload = get_crowdin_file_info(repository)
    
    return before_upload, after_upload

def crowdin_download_translations(repository, all_files, new_files, file_info):
    updated_files = list(new_files)

    for file in set(all_files).difference(set(new_files)):
        crowdin_file = get_crowdin_file(repository, file)

        if crowdin_file not in file_info:
            continue

        metadata = file_info[crowdin_file]

        if metadata['phrases'] == metadata['approved']:
            updated_files.append(file)
            continue

        target_file = 'ja/' + file[3:] if file[0:3] == 'en/' else file.replace('/en/', '/ja/')

        if not os.path.isfile(target_file):
            updated_files.append(file)
            continue

    if len(updated_files) > 0:
        configure_crowdin(repository, updated_files)

        _crowdin('download', '-l', 'ja')

crowdin_base_url = 'https://api.crowdin.com/api/project/'

def crowdin_request(repository, api_path, request_type='GET', data=None, files=None):
    headers = {
        'user-agent': 'python'
    }

    request_url = crowdin_base_url + repository.crowdin.project_name + api_path
    
    if request_type == 'GET':
        get_data = { 'key': repository.crowdin.api_key }

        if data is not None:
            get_data.update(data)
            
        request_url = request_url + '?' + '&'.join([key + '=' + value for key, value in get_data.items()])

        r = requests.get(request_url, data=get_data, headers=headers)
    else:
        request_url = request_url + '?key=' + repository.crowdin.api_key
        r = requests.post(request_url, data=data, files=files, headers=headers)

    if r.status_code < 200 or r.status_code >= 400:
        logging.error('HTTP Error: %d' % r.status_code)
        return (r.status_code, None)

    return (r.status_code, r.content)

def save_translation_memory(repository):
    logging.info('crowdin-api download-tm')

    data = {
        'source_language': 'en',
        'target_language': 'ja'
    }

    status_code, response_content = crowdin_request(repository, '/download-tm', 'GET', data)

    if response_content is not None:
        with open('%s/%s.tmx' % (initial_dir, repository.crowdin.project_name), 'wb') as f:
            f.write(response_content)

def save_glossary(repository):
    logging.info('crowdin-api download-glossary')

    status_code, response_content = crowdin_request(repository, '/download-glossary', 'GET')

    if response_content is not None:
        with open('%s/%s.tbx' % (initial_dir, repository.crowdin.project_name), 'wb') as f:
            f.write(response_content)

def delete_translation(repository, file):
    logging.info('crowdin-api delete-file %s' % file)

    data = {
        'file': file
    }

    return crowdin_request(repository, '/delete-file', 'POST', data)

def delete_translation_folder(repository, folder):
    logging.info('crowdin-api delete-directory %s' % folder)

    data = {
        'name': folder
    }

    return crowdin_request(repository, '/delete-directory', 'POST', data)

def extract_crowdin_file_info(files_element, current_path, file_info):
    for item in files_element.children:
        if item.name != 'item':
            continue

        item_name = item.find('name').text
        item_node_type = item.find('node_type').text

        item_path = current_path + '/' + item_name if current_path is not None else item_name

        file_info[item_path] = {
            'phrases': int(item.find('phrases').text),
            'translated': int(item.find('translated').text),
            'approved': int(item.find('approved').text)
        }

        if item_node_type == 'file':
            file_info[item_path]['id'] = item.find('id').text
        else:
            extract_crowdin_file_info(item.find('files'), item_path, file_info)

def get_crowdin_file_info(repository):
    logging.info('crowdin-api language-status')

    data = {
        'language': 'ja'
    }

    status_code, response_content = crowdin_request(
        repository, '/language-status', 'POST', data)

    file_info = {}

    if response_content is not None:
        soup = BeautifulSoup(response_content, features='html.parser')
        extract_crowdin_file_info(soup.find('files'), None, file_info)

    return file_info

# Send requests to CrowdIn to do automated translation (translation memory,
# machine translation).

def translate_with_memory(repository, files):
    data = {
        'languages[]': ['ja'],
        'files[]': files,
        'method': 'tm',
        'auto_approve_option': 0,
        'import_duplicates': 1,
        'apply_untranslated_strings_only': 1,
        'perfect_match': 0,
        'json': 1
    }

    return crowdin_request(repository, '/pre-translate', 'POST', data)

def translate_with_machine(repository, files):
    data = {
        'languages[]': ['ja'],
        'files[]': files,
        'method': 'mt',
        'engine': 'google',
        'json': 1
    }

    return crowdin_request(repository, '/pre-translate', 'POST', data)

def crowdin_http_request(repository, path, **data):
    get_data = { key: value for key, value in data.items() }

    get_data['project_id'] = repository.crowdin.project_id
    get_data['target_language_id'] = '25'

    query_string = '&'.join([key + '=' + str(value) for key, value in get_data.items()])
    
    url = 'https://www.crowdin.com%s?%s' % (path, query_string)

    session.cookies.set('csrf_token', 'abcdefghij', domain='.crowdin.com', path='/')

    try:
        r = session.get(url, headers={'x-csrf-token': 'abcdefghij'})

        if r.url.find('/login') == -1:
            return r.content
    except:
        pass
    
    logging.info('Session timed out, refreshing session')
    r = session.get('https://accounts.crowdin.com/login')
    
    soup = BeautifulSoup(r.text, features='html.parser')
    token_input = soup.find('input', attrs={'name': '_token'})
    
    if token_input is None:
        return crowdin_http_request(repository, path, **data)
    
    data = {
        'email_or_login': git.config('crowdin.login'),
        'password': git.config('crowdin.password'),
        'continue': url,
        'locale': 'en',
        'intended': '/auth/token',
        '_token': token_input.attrs['value']
    }

    r = session.post('https://accounts.crowdin.com/login', data=data)
    
    return r.content

# Mass delete suggestions

def process_suggestions(repository, crowdin_file_name, file_info, translation_filter, translation_post_process, suggestion_filter):
    file_id = file_info[crowdin_file_name]['id']

    response_content = crowdin_http_request(
        repository, '/backend/phrases/phrases_as_html', file_id=file_id)

    soup = BeautifulSoup(response_content, features='html.parser')   

    translations = [
        tag for tag in soup.find_all(attrs={'class': 'crowdin_phrase'})
    ]

    translation_ids = [
        tag.attrs['id'][len('crowdin_phrase_'):] for tag in translations
            if translation_filter(tag)
    ]

    has_suggestions = False

    for translation_id in translation_ids:
        response_content = crowdin_http_request(
            repository, '/backend/translation/phrase', translation_id=translation_id)

        try:
            response_data = json.loads(response_content.decode('utf-8'))['data']
            raw_suggestions = response_data['suggestions']
        except:
            logging.error('Error trying to parse phrase %s for file %s' (translation_id, file_name))
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

        if len(suggestions) > 0:
            has_suggestions = True

        for suggestion in suggestions:
            logging.info('Deleting suggestion %s from user %s' % (suggestion['id'], suggestion['user']['login']))
            crowdin_http_request(
                repository, '/backend/suggestions/delete', translation_id=translation_id,
                plural_id='-1', suggestion_id=suggestion['id'])

        if translation_post_process is not None:
            translation_post_process(translation_id, response_data)

# Clear out auto-translations so we have a better sense of progress

def delete_auto_translations(repository, file_info):
    for crowdin_file_name in [key for key, value in file_info.items() if key.find(repository.crowdin.dest_folder) == 0 and 'id' in value]:
        logging.info('Removing auto-translations for file %s' % crowdin_file_name)

        process_suggestions(
            repository, crowdin_file_name, file_info,
            lambda x: True,
            None,
            lambda x: x['user']['login'] == 'is-user')

def delete_code_translations(repository, file_name, file_info):
    crowdin_file_name = get_crowdin_file(repository, file_name)
    
    if crowdin_file_name not in file_info:
        return False

    logging.info('Checking auto code translations for file %s' % file_name)

    def is_within_code_tag(x):
        return x.text and x.text.find('[TOC') == 0 or \
            x.name == 'code' or x.name == 'pre' or \
            x.find_parent('code') is not None or x.find_parent('pre') is not None or \
            x.find_parent(attrs={'id': 'front-matter'}) is not None

    def is_rst_directive(x):
        return x.text and ( \
            x.text.find('====') != -1 or x.text.find('----') != -1 or \
            x.text == '..' or x.text.find('::') != -1 or x.text.find(':') == 0 or \
            x.text.find(':doc:') != -1 or x.text.find(':ref:') != -1 or \
            x.text.lower() == x.text or \
            x.text[-3:] == '.md' or x.text[-4:] == '.rst' \
        )

    def hide_translation(translation_id, response_data):
        if not response_data['translation']['hidden']:
            crowdin_http_request(
                repository, '/backend/translation/change_visibility', translation_id=translation_id,
                hidden=1)

    def is_auto_translation(x):
        return x['user']['login'] == 'is-user'

    if file_name[-4:] == '.rst':
        has_suggestions = process_suggestions(
            repository, crowdin_file_name, file_info,
            is_rst_directive, hide_translation, is_auto_translation)
    else:
        has_suggestions = process_suggestions(
            repository, crowdin_file_name, file_info,
            is_within_code_tag, hide_translation, is_auto_translation)

    if not has_suggestions:
        return False

    target_file = 'ja/' + file_name[3:] if file_name[0:3] == 'en/' else file_name.replace('/en/', '/ja/')

    if os.path.exists(target_file):
        os.remove(target_file)

    return True

def pre_translate(repository, translation_needed, file_info):
    candidate_files = {
        file: get_crowdin_file(repository, file) for file in translation_needed
    }

    translation_files = {
        file: crowdin_file
            for file, crowdin_file in candidate_files.items()
                if crowdin_file in file_info
    }
    
    if len(translation_files) == 0:
        return

    for file in translation_files.keys():
        delete_code_translations(repository, file, file_info)

    translation_crowdin_files = translation_files.values()
    
    translate_with_machine(repository, translation_crowdin_files)
    
    for file in translation_files.keys():
        delete_code_translations(repository, file, file_info)

def pre_translate_folder(repository, folder, candidate_files, file_info):
    prefix = folder + '/'
    translation_needed = []

    for file in candidate_files:
        if file.find(prefix) != 0:
            continue

        crowdin_file = get_crowdin_file(repository, file)

        if crowdin_file not in file_info:
            continue

        target_file = 'ja/' + file[3:] if file[0:3] == 'en/' else file.replace('/en/', '/ja/')

        if not os.path.isfile(target_file):
            translation_needed.append(file)

    if len(translation_needed) > 0:
        logging.info('crowdin-api pre-translate %s' % folder)
        pre_translate(repository, translation_needed, file_info)

    return translation_needed

def get_orphaned_files(repository, update_result):
    new_files, all_files, file_info = update_result

    crowdin_files = [
        key for key, value in file_info.items()
            if key.find(repository.crowdin.dest_folder) == 0 and 'id' in value
    ]

    local_files = [
        get_local_file(repository, key) for key in crowdin_files        
    ]

    deleted_files = [
        file for file in local_files if not os.path.isfile('%s/%s' % (repository.github.git_root, file))
    ]

    crowdin_rename_candidates = defaultdict(list)

    for file in crowdin_files:
        crowdin_rename_candidates[file[file.rfind('/')+1:]].append(file)

    deleted_file_candidates = {
        get_crowdin_file(repository, file): [
            candidate for candidate in crowdin_rename_candidates[file[file.rfind('/')+1:]]
                if candidate != get_crowdin_file(repository, file)
        ] for file in deleted_files
    }

    return [
        (key, value[0]) for key, value in deleted_file_candidates.items()
            if len(value) == 1
    ]

def get_orphaned_files_as_data_frame(repository, update_result):
    def get_data_row(file_info, file1, file2, columns):
        return [file1[file1.rfind('/')+1:]] + [
            file_info[file][column] for column in columns for file in [file1, file2]
        ]

    columns = ['id', 'translated', 'approved', 'phrases']

    return pd.DataFrame([
        get_data_row(file_info, file1, file2, columns)
            for file1, file2 in get_orphaned_files(repository, update_result)
    ], columns = ['name'] + ['%s%d' % (column, i) for column in columns for i in [1, 2]])

def delete_orphaned_files(repository, update_result):
    for file1, file2 in get_orphaned_files(repository, update_result):
        delete_translation(repository, file1)

