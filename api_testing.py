
from bs4 import BeautifulSoup
from collections import namedtuple
from datetime import datetime
from collections import defaultdict
import json
import logging
import math
import os
import pandas as pd
import requests
from scrape_liferay import authenticate, session
from subprocess import Popen, PIPE
import time

try:
    from subprocess import DEVNULL
except ImportError:
    import os
    DEVNULL = open(os.devnull, 'wb')

logging.basicConfig(
    format='%(asctime)s %(levelname)-8s %(message)s',
    level=logging.INFO,
    datefmt='%Y-%m-%d %H:%M:%S')

initial_dir = os.getcwd()

test_folders = None

def _git(*args, stderr=PIPE):
    cmd = ['git'] + list(args)

    if args[0] != 'config':
        logging.info(' '.join(cmd))

    pipe = Popen(cmd, stdout=PIPE, stderr=stderr)
    out, err = pipe.communicate()

    return out.decode('UTF-8', 'replace')

GitHubRepository = namedtuple(
    'GitHubRepository',
    ' '.join(['git_root', 'origin', 'upstream', 'branch', 'project_folder', 'single_folder'])
)

CrowdInRepository = namedtuple(
    'CrowdinRepository',
    ' '.join(['project_id', 'api_key', 'dest_folder'])
)

TranslationRepository = namedtuple(
    'TranslationRepository',
    ' '.join(['github', 'crowdin'])
)

def get_repository(git_repository, git_branch, git_folder, project_id, project_folder, single_folder):
    single_folder = single_folder.strip()

    if len(single_folder) == 0:
        single_folder = None
    else:
        single_folder = git_folder + '/' + single_folder
    
    git_root = os.path.dirname(initial_dir) + '/' + git_repository

    os.chdir(git_root)

    logging.info(git_root)

    origin_url = _git('remote', 'get-url', 'origin').strip()
    origin = origin_url.split(':')[1][:-4]

    upstream_url = _git('remote', 'get-url', 'upstream').strip()
    
    if len(upstream_url) == 0:
        upstream = None
    else:
        upstream = upstream_url.split(':')[1][:-4]

    project_api_key = _git('config', 'crowdin.api-key.%s' % project_id).strip()

    os.chdir(initial_dir)

    return TranslationRepository(
        GitHubRepository(git_root, origin, upstream, git_branch, git_folder, single_folder),
        CrowdInRepository(project_id, project_api_key, project_folder)
    )

os.chdir(initial_dir)
repositories_df = pd.read_csv('repositories.csv')
repositories_df.fillna('', inplace=True)
repositories_df

repositories = [get_repository(**x) for x in repositories_df.to_dict('records')]
repositories

github_oauth_token = _git('config', 'github.oauth-token').strip()
assert(github_oauth_token is not None)

github_base_url = 'https://api.github.com'

def github_request(api_path, request_type=None, data=None):
    headers = {
        'user-agent': 'python',
        'authorization': 'token %s' % github_oauth_token,
        'accept': 'application/vnd.github.inertia-preview+json'
    }

    logging.info('github-api %s' % api_path)

    if data is None:
        r = requests.get(github_base_url + api_path, headers=headers)
    elif request_type == 'PATCH':
        r = requests.patch(github_base_url + api_path, json=data, headers=headers)
    elif request_type == 'POST':
        r = requests.post(github_base_url + api_path, json=data, headers=headers)

    if r.status_code < 200 or r.status_code >= 400:
        logging.error('HTTP Error: %d' % r.status_code)
        return (r.status_code, r.headers, None)

    return (r.status_code, r.headers, r.json())

global remaining

remaining = 0

def wait_for_rate_limit_reset():
    global remaining

    if remaining > 0:
        remaining -= 1
        return

    while True:
        status_code, headers, result = github_request('/rate_limit')

        resources = result['resources']['core']
        remaining = resources['remaining']

        if remaining > 0:
            remaining -= 1
            return

        wait_time = 1 + int(resources['reset'] - datetime.now().timestamp())

        logging.error('Waiting %d seconds for rate limit reset' % wait_time)

        time.sleep(wait_time)

def filter_github_request(api_path, request_type=None, data=None, field_name=None, min_field_value=None):
    global remaining

    if remaining == 0:
        wait_for_rate_limit_reset()

    status_code, headers, result = github_request(api_path, request_type, data)

    if result is None:
        remaining = int(headers['X-RateLimit-Remaining']) if 'X-RateLimit-Remaining' in headers else 0

        if remaining == 0:
            wait_for_rate_limit_reset()
            status_code, headers, result = github_request(api_path, request_type, data)

    if result is None:
        return (status_code, headers, [])

    if min_field_value is None:
        return (status_code, headers, result)

    return (status_code, headers, [item for item in result if item[field_name] > min_field_value])

def filter_github_request_all(api_path, request_type=None, data=None, field_name=None, min_field_value=None):
    results = []

    while api_path is not None:
        status_code, headers, new_results = filter_github_request(
            api_path, request_type, data, field_name, min_field_value)

        results.extend(new_results)

        lower_headers = {
            key.lower(): value for key, value in headers.items()
        }

        if 'link' not in lower_headers:
            break

        api_path = None

        for link in lower_headers['link'].split(','):
            url_info, rel_info = [info.strip() for info in link.split(';')]

            rel = rel_info.split('"')[1]
            if rel == 'next':
                api_path = url_info[len('<https://api.github.com'):-1]

    return status_code, headers, results

def is_repository_accessible(reviewer_url):
    if reviewer_url is None:
        return True
    
    api_path = '/repos/%s' % reviewer_url

    status_code, headers, result = filter_github_request(api_path)

    return result is not None

for git_repository, crowdin_repository in repositories:
    assert(is_repository_accessible(git_repository.origin))
    assert(is_repository_accessible(git_repository.upstream))

def _crowdin(*args, stderr=PIPE):
    cmd = ['crowdin'] + list(args)

    logging.info(' '.join(cmd))

    pipe = Popen(cmd, stdout=PIPE, stderr=stderr)
    out, err = pipe.communicate()

    return out.decode('UTF-8', 'replace').strip()

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

def get_crowdin_file(repository, local_file):
    return repository.crowdin.dest_folder + '/' + local_file[len(repository.github.project_folder)+1:]

def get_local_file(repository, crowdin_file):
    return repository.github.project_folder + crowdin_file[len(repository.crowdin.dest_folder):]

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
"project_identifier" : "{crowdin_project_id}"
"api_key" : "{crowdin_api_key}"
"base_path" : "{git_root}"
"preserve_hierarchy": true

"files": {files}
'''.format(
        crowdin_project_id=repository.crowdin.project_id,
        crowdin_api_key=repository.crowdin.api_key,
        git_root=repository.github.git_root,
        files=config_json
    ))

def get_root_folders(repository, candidate_files):
    candidate_folders = get_folders(candidate_files)

    root_folders = set()
    
    prefix = repository.github.project_folder + '/'

    single_folder = repository.github.single_folder
    
    if single_folder is None:
        prefix = repository.github.project_folder + '/'
    else:
        prefix = repository.github.single_folder + '/'
    
    for folder in candidate_folders:
        if folder == repository.github.project_folder:
            continue

        if folder != single_folder and folder.find(prefix) != 0:
            continue

        parent_folder = folder

        while parent_folder != repository.github.project_folder:
            folder = parent_folder
            parent_folder = os.path.dirname(folder)

        if parent_folder != '':
            root_folders.add(folder)

    return list(root_folders)

def crowdin_upload_sources(repository, new_files):
    before_upload = get_crowdin_file_info(repository)

    for file in new_files:
        extension = file[file.rfind('.'):]

        if extension == '.md' or extension == '.markdown':
            _pandoc(file, '--from=gfm', '--to=gfm', '--wrap=none')

    if len(new_files) > 0:
        root_folders = get_root_folders(repository, new_files)

        for root_folder in root_folders:
            prefix = root_folder + '/'
            folder_files = [file for file in new_files if file.find(prefix) == 0]
            
            configure_crowdin(repository, folder_files)
            _crowdin('upload', 'sources')

    _git('reset', '--hard')

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

    request_url = crowdin_base_url + repository.crowdin.project_id + api_path +         '?key=' + repository.crowdin.api_key

    if request_type == 'GET':
        r = requests.get(request_url, data=data, headers=headers)
    else:
        r = requests.post(request_url, data=data, files=files, headers=headers)

    if r.status_code < 200 or r.status_code >= 400:
        logging.error('HTTP Error: %d' % r.status_code)
        return (r.status_code, None)

    return (r.status_code, r.text)

def save_translation_memory(repository):
    logging.info('crowdin-api download-tm')

    data = {
        'source_language': 'en',
        'target_language': 'ja'
    }

    status_code, response_text = crowdin_request(repository, '/download-tm', 'GET', data)

    if response_text is not None:
        with open('%s/%s.tmx' % (initial_dir, repository.crowdin.project_id), 'w') as f:
            f.write(response_text)

def save_glossary(repository):
    logging.info('crowdin-api download-glossary')

    status_code, response_text = crowdin_request(repository, '/download-glossary', 'GET')

    if response_text is not None:
        with open('%s/%s.tbx' % (initial_dir, repository.crowdin.project_id), 'w') as f:
            f.write(response_text)

def delete_translation(repository, file):
    logging.info('crowdin-api delete-file %s' % file)

    data = {
        'file': file
    }

    return crowdin_request(repository, '/delete-file', 'POST', data)

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

    status_code, response_text = crowdin_request(
        repository, '/language-status', 'POST', data)

    file_info = {}

    if response_text is not None:
        soup = BeautifulSoup(response_text, features='html.parser')
        extract_crowdin_file_info(soup.find('files'), None, file_info)

    return file_info

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

def pre_translate(repository, translation_needed, file_info):
    candidate_files = [get_crowdin_file(repository, file) for file in translation_needed]
    translation_files = [file for file in candidate_files if file in file_info]

    if len(translation_files) == 0:
        return

    #translate_with_machine(repository, translation_files)
    #translate_with_memory(repository, translation_files)

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

def get_files(folder):
    files = []

    for name in os.listdir(folder):
        path = '%s/%s' % (folder, name)

        if os.path.isdir(path):
            files.extend(get_files(path))
        else:
            files.append(path)

    return list(files)

def get_folders(files):
    return sorted(set([os.path.dirname(file) if os.path.isfile(file) else file for file in files]))

def is_translation_eligible(repository, file, language_id):
    prefix = repository.github.project_folder

    if file.find(prefix) == 0:
        if file[0:3] == language_id + '/' or file.find('/' + language_id + '/') != -1:
            if file[-9:] == '.markdown' or file[-3:] == '.md' or file[-5:] == '.html':
                return True

    return False

def get_eligible_files(repository, output, language_id):
    if test_folders is not None:
        for test_folder in set(test_folders):
            test_files.update(get_files(test_folder))

        output = '\n'.join(test_files)

    return [
        file for file in output.split('\n')
            if is_translation_eligible(repository, file, language_id)
    ]

def get_milestone_number(repository, milestone_map, milestone_title):
    if milestone_title in milestone_map:
        return milestone_map[milestone_title]

    api_path = '/repos/%s/milestones' % repository.github.origin

    data = {
        'title': milestone_title
    }

    status_code, headers, milestone = filter_github_request(api_path, 'POST', data)

    milestone_map[milestone_title] = milestone['number']

    return milestone['number']

def get_milestone_map(repository):
    milestone_map_folder = '%s/%s' % (initial_dir, repository.github.origin)
    
    if not os.path.exists(milestone_map_folder):
        os.makedirs(milestone_map_folder)
    
    milestone_map_file = '%s/milestones.json' % milestone_map_folder
    milestone_map = {}

    if os.path.exists(milestone_map_file):
        with open(milestone_map_file, 'r') as f:
            milestone_map = json.load(f)
    else:
        api_path = '/repos/%s/milestones?state=all' % repository.github.origin

        status_code, headers, milestones = filter_github_request(api_path)

        milestone_map = {
            milestone['title']: milestone['number']
                for milestone in milestones
        }

    get_milestone_number(repository, milestone_map, 'human')
    get_milestone_number(repository, milestone_map, 'machine')

    with open(milestone_map_file, 'w') as f:
        json.dump(milestone_map, f)

    return milestone_map

def get_issue_map(repository):
    issue_map_file = '%s/%s/issues.json' % (initial_dir, repository.github.origin)
    issue_map = {}

    if os.path.exists(issue_map_file):
        with open(issue_map_file, 'r') as f:
            issue_map = json.load(f)

    if repository.github.branch not in issue_map:
        return {}

    prefix = repository.github.project_folder + '/'

    return {
        key: value for key, value in issue_map[repository.github.branch].items()
            if key.find(prefix) == 0
    }

def save_issue_map(repository, updated_issues):
    issue_map_file = '%s/%s/issues.json' % (initial_dir, repository.github.origin)
    issue_map = {}

    if os.path.exists(issue_map_file):
        with open(issue_map_file, 'r') as f:
            issue_map = json.load(f)

    if repository.github.branch not in issue_map:
        issue_map[repository.github.branch] = {}

    issue_map[repository.github.branch].update(updated_issues)

    with open(issue_map_file, 'w') as f:
        json.dump(issue_map, f)

def get_issue_line(repository, prefix, key, metadata):
    translation_completion = int(100 * metadata['translated'] / metadata['phrases'])
    proofread_completion = int(100 * metadata['approved'] / metadata['phrases'])

    status_string = '(%d%% translated, %d%% proofread)' % (translation_completion, proofread_completion)

    if 'id' not in metadata:
        return '\n**%s** %s\n' % (key[prefix.rfind('/')+1:], status_string)
    else:
        return '* [%s](https://crowdin.com/translate/%s/%s/en-ja) %s' %             (key[key.rfind('/')+1:], repository.crowdin.project_id, metadata['id'], status_string)

def get_issue_body(repository, folder, file_info):
    prefix = get_crowdin_file(repository, folder)

    matching_files = sorted([
        (key, metadata) for key, metadata in file_info.items() if key.find(prefix) == 0
    ])

    if len(matching_files) == 0:
        return ''

    external_links = [
        get_issue_line(repository, prefix, key, metadata)
            for key, metadata in matching_files
    ]

    return '\n'.join(external_links).strip()

def init_issue(repository, folder, file_info):
    issue_map = get_issue_map(repository)

    if folder in issue_map:
        return issue_map[folder]

    data = {
        'title': '%s - %s' % (repository.github.branch, folder),
        'body': get_issue_body(repository, folder, file_info),
        'milestone': get_milestone_map(repository)['machine']
    }

    api_path = '/repos/%s/issues' % repository.github.origin
    status_code, headers, result = filter_github_request(api_path, 'POST', data)

    issue_map[folder] = result['number']

    save_issue_map(repository, issue_map)

    return issue_map[folder]

def init_issues(repository, all_files, file_info):
    root_folders = get_root_folders(repository, all_files)

    new_translations = []

    for folder in root_folders:
        issue_number = init_issue(repository, folder, file_info)
        new_translations.extend(pre_translate_folder(repository, folder, all_files, file_info))

    return new_translations

def get_milestone_numbers(repository, all_files, file_info):
    root_folders = get_root_folders(repository, all_files)

    milestone_numbers = {}

    for folder in root_folders:
        issue_number = init_issue(repository, folder, file_info)

        api_path = '/repos/%s/issues/%d' % (repository.github.origin, issue_number)
        status_code, headers, result = filter_github_request(api_path)

        state = result['state']

        milestone = result['milestone'] if 'milestone' in result else None
        milestone_number = milestone['number'] if milestone is not None else None

        milestone_numbers[folder] = (state, milestone_number)

    return milestone_numbers

def reopen_issue(repository, folder, file_info):
    issue_number = init_issue(repository, folder, file_info)

    api_path = '/repos/%s/issues/%d' % (repository.github.origin, issue_number)
    status_code, headers, result = filter_github_request(api_path)

    milestone = result['milestone'] if 'milestone' in result else None
    milestone_number = milestone['number'] if milestone is not None else None

    issue_body = get_issue_body(repository, folder, file_info)

    if result['state'] != 'closed' and result['body'] == issue_body and milestone_number is not None:
        return issue_number

    data = {
        'state': 'open',
        'body': issue_body
    }

    if milestone_number is None:
        data['milestone'] = get_milestone_map(repository)['machine']

    status_code, headers, result = filter_github_request(api_path, 'PATCH', data)

    return issue_number

def reopen_issues(repository, new_files, file_info):
    root_folders = get_root_folders(repository, new_files)

    new_translations = []

    for folder in root_folders:
        reopen_issue(repository, folder, file_info)
        new_translations.extend(pre_translate_folder(repository, folder, new_files, file_info))

    return new_translations

def close_issue(repository, folder, file_info):
    issue_number = init_issue(repository, folder, file_info)

    api_path = '/repos/%s/issues/%d' % (repository.github.origin, issue_number)

    data = {
        'state': 'closed'
    }

    status_code, headers, result = filter_github_request(api_path, 'PATCH', data)

    return issue_number

def get_github_project_map(origin):
    status_code, headers, projects = filter_github_request('/repos/%s/projects' % origin)

    project_map = {}

    for project in projects:
        project_name = project['name']

        separator_pos = project_name.find(' - ')

        branch = project_name[:separator_pos]
        folder = project_name[separator_pos+3:]

        if branch not in project_map:
            project_map[branch] = {}

        project_map[branch][folder] = project['id']

    return project_map

def init_github_project(project_map, repository):
    if repository.github.branch in project_map:
        for project_folder, project_number in project_map[repository.github.branch].items():
            if project_folder == repository.github.project_folder:
                return project_number
    else:
        project_map[repository.github.branch] = {}

    api_path = '/repos/%s/projects' % repository.github.origin

    data = {
        'name': '%s - %s' % (repository.github.branch, repository.github.project_folder)
    }

    status_code, headers, project = filter_github_request(api_path, 'POST', data)
    project_map[repository.github.branch][repository.github.project_folder] = project['id']

    return project['id']

def init_github_column(columns, project_number, column_index, column_name):
    for column in columns:
        if column_name == column['name']:
            return column

    api_path = '/projects/%s/columns' % project_number

    data = {
        'name': column_name
    }

    status_code, headers, column = filter_github_request(api_path, 'POST', data)

    if len(columns) != column_index:
        api_path = '/projects/columns/%s/moves' % column['id']

        data = {
            'position': 'first' if column_index == 0 else 'after:%d' % (column_index - 1)
        }

    columns.insert(column_index, column)

    return column

def init_github_columns(column_map, project_number):
    if project_number in column_map:
        columns = column_map[project_number]
    else:
        status_code, headers, columns = filter_github_request('/projects/%s/columns' % project_number)
        column_map[project_number] = columns

    init_github_column(columns, project_number, 0, 'Selected for translation')
    init_github_column(columns, project_number, 1, 'Translation started')
    init_github_column(columns, project_number, 2, 'Ready for proofreading')
    init_github_column(columns, project_number, 3, 'Proofreading started')
    init_github_column(columns, project_number, 4, 'Merge request sent')
    init_github_column(columns, project_number, 5, 'Merge completed')

    return columns

def get_github_card(card_map, repository, project_number, issue_number, target_column_index, columns):
    if project_number not in card_map:
        card_map[project_number] = {}

        for column in columns:
            column_id = column['id']
            column_name = column['name']

            status_code, headers, cards = filter_github_request('/projects/columns/%s/cards' % column_id)

            card_map[project_number].update({
                int(card['content_url'][card['content_url'].rfind('/')+1:]): {
                    'card_id': card['id'], 'column_id': column_id
                } for card in cards if 'content_url' in card
            })

    if issue_number in card_map[project_number]:
        return card_map[project_number][issue_number]

    api_path = '/repos/%s/issues/%d' % (repository.github.origin, issue_number)
    status_code, headers, issue = filter_github_request(api_path)

    column_index = target_column_index if target_column_index is not None else 0

    api_path = '/projects/columns/%s/cards' % columns[column_index]['id']

    data = {
        'content_id': issue['id'],
        'content_type': 'Issue'
    }

    status_code, headers, card = filter_github_request(api_path, 'POST', data)

    card_map[project_number][issue_number] = {
        'card_id': card['id'], 'column_id': columns[column_index]['id']
    }

    return card

def update_issue_column(project_map, column_map, card_map, repository, folder, issue_number, target_column_index):
    project_number = init_github_project(project_map, repository)
    columns = init_github_columns(column_map, project_number)
    target_column_id = None if target_column_index is None else columns[target_column_index]['id']

    card = get_github_card(card_map, repository, project_number, issue_number, target_column_index, columns)

    if target_column_id is None or card['column_id'] == target_column_id:
        return

    api_path = '/projects/columns/cards/%s/moves' % card['card_id']

    data = {
        'position': 'top',
        'column_id': target_column_id
    }

    status_code, headers, update_info = filter_github_request(api_path, 'POST', data)

def update_issue_columns(repository, file_info, target_column_map):
    project_map = get_github_project_map(repository.github.origin)
    column_map = {}
    card_map = {}

    for folder, target_column_index in target_column_map.items():
        init_issue(repository, folder, file_info)
        issue_map = get_issue_map(repository)
        issue_number = issue_map[folder]

        update_issue_column(
            project_map, column_map, card_map, repository,
            folder, issue_number, target_column_index)

def update_translation_issues(repository, file_info):
    issues = []

    api_path = '/repos/%s/issues?milestone=%d' %         (repository.github.origin, get_milestone_map(repository)['human'])

    status_code, headers, issues = filter_github_request_all(api_path)

    target_column_map = {}

    issue_map = get_issue_map(repository)

    folder_map = {
        value: key for key, value in issue_map.items()
    }

    for issue in issues:
        issue_number = issue['number']

        if issue_number not in folder_map:
            continue

        folder = folder_map[issue_number]
        key = get_crowdin_file(repository, folder)

        if key in file_info:
            approved = file_info[key]['approved']
            translated = file_info[key]['translated']
            phrases = file_info[key]['phrases']

            if approved == phrases:
                target_column_map[folder] = 4
            elif approved > 0:
                target_column_map[folder] = 3
            elif translated == phrases:
                target_column_map[folder] = 2
            elif translated > 0:
                target_column_map[folder] = 1
            else:
                target_column_map[folder] = 0
        else:
            target_column_map[folder] = None

    update_issue_columns(repository, file_info, target_column_map)

def set_default_parameter(parameters, name, default_value):
    if name not in parameters:
        parameters[name] = default_value

def zendesk_request(api_path, attribute_name, params=None):
    parameters = {}
    
    if params is not None:
        parameters.update(params)
    
    result = []

    set_default_parameter(parameters, 'per_page', 100)    
    set_default_parameter(parameters, 'sort_by', 'created_at')
    set_default_parameter(parameters, 'page', 1)

    api_result = None
    page_count = None

    incremental = api_path.find('/incremental/') != -1
    
    while page_count is None or parameters['page'] <= page_count:
        query_string = '&'.join('%s=%s' % (key, value) for key, value in parameters.items())
        url = 'https://liferay-support.zendesk.com/api/v2%s?%s' % (api_path, query_string)

        if url is None:
            break

        r = session.get(url)
        print(url)

        api_result = json.loads(r.text)

        if attribute_name in api_result:
            if type(api_result[attribute_name]) == list:
                result = result + api_result[attribute_name]
            else:
                result.append(api_result[attribute_name])
        else:
            print(r.text)
            return None

        parameters['page'] = parameters['page'] + 1

        if 'page_count' in api_result:
            page_count = api_result['page_count']
        elif 'count' in api_result:
            page_count = math.ceil(api_result['count'] / parameters['per_page'])
        else:
            page_count = 1

    return result

def init_zendesk():
    print('Authenticating with Liferay SAML IdP')
    authenticate('https://liferay-support.zendesk.com/access/login', None)
    
    return zendesk_request('/users/me.json', 'user')[0]

def get_zendesk_articles():
    user = init_zendesk()
    print('Authenticated as %s' % user['email'])
    assert(user['verified'])

    # Reload the articles we already know about
    
    articles = {}

    try:
        with open('%s/articles.json' % initial_dir, 'r') as f:
            articles = json.load(f)
    except:
        pass
    
    # Fetch new articles with the incremental API
    
    article_parameters = {
        'start_time': 0 if len(articles) == 0 else max([article['updated_at'] for article in articles.values()])
    }
    
    new_articles = zendesk_request('/help_center/incremental/articles.json', 'articles', article_parameters)
    
    # Override past articles
    
    articles.update({article['id']: article for article in new_articles})
    
    # Cache the articles on disk so we can work on them without having to go back to the API
    
    with open('articles.json', 'w') as f:
        json.dump(articles, f)
    
    return articles

def update_zendesk_articles():
    user = init_zendesk()
    print('Authenticated as %s' % user['email'])
    assert(user['verified'])

    # Determine the proper folder structure

    categories = zendesk_request('/help_center/en-us/categories.json', 'categories')
    category_paths = {
        category['id']: 'en/' + category['html_url'][category['html_url'].rfind('/'):]
            for category in categories
    }

    sections = zendesk_request('/help_center/en-us/sections.json', 'sections')
    section_paths = {
        section['id']: category_paths[section['category_id']] + section['html_url'][section['html_url'].rfind('/'):]
            for section in sections
    }
    
    articles = get_zendesk_articles()

    article_paths = {
        str(article['id']): section_paths[article['section_id']] + article['html_url'][article['html_url'].rfind('/'):] + '.html'
            for article in articles.values()
                if article['section_id'] in section_paths and not article['draft'] and article['locale'] == 'en-us' and 'Fast Track' not in article['label_names']
    }

    article_paths.update({
        str(article['id']): 'en/' + ('0'*12) + '-Fast-Track' + article['html_url'][article['html_url'].rfind('/'):] + '.html'
            for article in articles.values()
                if article['section_id'] in section_paths and not article['draft'] and article['locale'] == 'en-us' and 'Fast Track' in article['label_names']
    })

    for article_id, article_path in article_paths.items():
        article_file_name = '/home/minhchau/Work/liferay/zendesk-articles/%s' % article_path
        article_folder = os.path.dirname(article_file_name)

        if not os.path.exists(article_folder):
            os.makedirs(article_folder)

        with open(article_file_name, 'w', encoding='utf-8') as f:
            f.write(articles[article_id]['body'])

def get_branch_files(repository):
    if repository.github.upstream is not None:
        _git('fetch', 'upstream', '--no-tags', '%s:refs/remotes/upstream/%s' %              (repository.github.branch, repository.github.branch))

        diff_output = _git('diff', '--name-only', '%s..upstream/%s' %             (repository.github.branch, repository.github.branch))
    else:
        diff_output = '\n'.join([line[3:] for line in _git('status', '-s') if len(line) > 3])

    new_files = get_eligible_files(repository, diff_output, 'en')

    lstree_output = _git('ls-tree', '-r', '--name-only', repository.github.branch)
    all_files = get_eligible_files(repository, lstree_output, 'en')

    return new_files, all_files

def update_sources(repository, new_files):
    _git('checkout', repository.github.branch)
    
    if repository.github.upstream:
        _git('merge', 'upstream/%s' % repository.github.branch)

    return crowdin_upload_sources(repository, new_files)

def update_translations(repository, all_files):
    now = datetime.now()

    status_output = '\n'.join([line[3:] for line in _git('status', '--porcelain').split('\n')])
    commit_files = get_eligible_files(repository, status_output, 'ja')

    if len(commit_files) == 0:
        return

    for file in commit_files:
        if file[-3:] == '.md':
            continue

        md_file = file[:-9] + '.md'

        if os.path.isfile(md_file):
            os.remove(md_file)
            os.rename(file, md_file)

    status_output = '\n'.join([line[3:] for line in _git('status', '--porcelain').split('\n')])
    commit_files = get_eligible_files(repository, status_output, 'ja')

    if len(commit_files) == 0:
        return

    _git('add', *commit_files)
    _git('commit', '-m', 'Updated translations %s' % now.strftime("%Y-%m-%d %H:%M:%S"))

def cleanup_files(repository, all_files, old_file_info, new_file_info):
    human_milestone_number = get_milestone_map(repository)['human']
    milestone_numbers = get_milestone_numbers(repository, all_files, new_file_info)

    new_keys = set(new_file_info.keys()).difference(set(old_file_info.keys()))

    to_delete = set()
    to_upload = set()

    for key, metadata in new_file_info.items():
        if key not in new_keys or 'id' not in metadata:
            continue

        if key.find(repository.crowdin.dest_folder) != 0:
            continue

        local_file = get_local_file(repository, key)
        folder = get_root_folders(repository, [local_file])[0]

        if folder not in milestone_numbers:
            continue

        state, milestone_number = milestone_numbers[folder]

        to_delete.add(key)

        if milestone_number == human_milestone_number:
            to_upload.add(local_file)

    for key in to_delete:
        delete_translation(repository, key)
        del new_file_info[key]

    return update_sources(repository, to_upload)

def update_repository(repository):
    logging.info('cd %s' % repository.github.git_root)
    os.chdir(repository.github.git_root)

    new_files, all_files = get_branch_files(repository)

    for file in new_files:
        target_file = 'ja/' + file[3:] if file[0:3] == 'en/' else file.replace('/en/', '/ja/')

        if os.path.isfile(target_file):
            os.remove(target_file)

    for file in set(all_files).difference(set(new_files)):
        target_file = 'ja/' + file[3:] if file[0:3] == 'en/' else file.replace('/en/', '/ja/')

        if not os.path.isfile(target_file):
            new_files.append(file)
    
    old_file_info, file_info = update_sources(repository, new_files)

    new_translations = init_issues(repository, all_files, file_info)
    new_translation_needed = list(set(new_files).difference(set(new_translations)))

    if len(get_root_folders(repository, new_translation_needed)) > 0:
        _, file_info = update_sources(repository, new_translation_needed)
        reopen_issues(repository, new_translation_needed, file_info)
        new_translations.extend(new_translation_needed)

    crowdin_download_translations(repository, all_files, new_files, file_info)

    update_translations(repository, all_files)
    cleanup_files(repository, all_files, old_file_info, file_info)
    update_translation_issues(repository, file_info)

    save_translation_memory(repository)
    save_glossary(repository)

    logging.info('cd -')
    os.chdir(initial_dir)

os.chdir(initial_dir)

update_zendesk_articles()

for repository in repositories:
    update_repository(repository)

