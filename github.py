from datetime import datetime
from file_manager import get_crowdin_file, get_root_folders
import git
import json
import logging
import os
import requests
from repository import initial_dir
from scrape_liferay import authenticate, session
import time

github_oauth_token = git.config('github.oauth-token')
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

# Issue API

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
        return '* [%s](https://crowdin.com/translate/%s/%s/en-ja) %s' % \
            (key[key.rfind('/')+1:], repository.crowdin.project_name, metadata['id'], status_string)

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

    for folder in root_folders:
        issue_number = init_issue(repository, folder, file_info)

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

    for folder in root_folders:
        reopen_issue(repository, folder, file_info)

def close_issue(repository, folder, file_info):
    issue_number = init_issue(repository, folder, file_info)

    api_path = '/repos/%s/issues/%d' % (repository.github.origin, issue_number)

    data = {
        'state': 'closed'
    }

    status_code, headers, result = filter_github_request(api_path, 'PATCH', data)

    return issue_number

# Project API (beta)

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
    target_column_id = None if target_column_index is None else str(columns[target_column_index]['id'])

    card = get_github_card(card_map, repository, project_number, issue_number, target_column_index, columns)

    if 'column_id' not in card:
        card['column_id'] = card['column_url'][card['column_url'].rfind('/')+1:]

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

    api_path = '/repos/%s/issues?milestone=%d' % \
        (repository.github.origin, get_milestone_map(repository)['human'])

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
