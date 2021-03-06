from crowdin import crowdin_request, delete_translation_folder
from crowdin_sync import update_repository
from github import is_repository_accessible
import json
from liferay_learn import add_disclaimers_to_learn, copy_crowdin_to_learn, copy_learn_to_crowdin
import os
import pandas as pd
from repository import get_repository, initial_dir
import sys
import time
from zendesk import copy_crowdin_to_zendesk, copy_zendesk_to_crowdin

uat_domain = 'liferaysupport1528999723.zendesk.com'
prod_domain = 'liferay-support.zendesk.com'

def get_repositories(check_accessible=True):
    status_code, response_text = crowdin_request(None, '/account/get-projects', 'GET', {'json': 'true'})

    projects = json.loads(response_text)['projects']

    repositories_df = pd.read_csv('%s/repositories.csv' % initial_dir, comment='#')
    repositories_df.fillna('', inplace=True)

    repositories = [get_repository(projects, **x) for x in repositories_df.to_dict('records')]

    if check_accessible:
        for git_repository, crowdin_repository in repositories:
            assert(is_repository_accessible(git_repository.origin))
            assert(is_repository_accessible(git_repository.upstream))

    return repositories

def list_jobs():
    all_repositories = get_repositories(False)

    print()
    print('Valid commands:')

    for repository in all_repositories:
        if repository is None:
            continue

        git_root = repository.github.git_root

        git_repository = git_root[git_root.rfind('/')+1:]
        git_folder = repository.github.project_folder if repository.github.single_folder is None else repository.github.single_folder

        if repository.github.origin == 'holatuwol/zendesk-articles':
            print('  python %s %s %s crowdin' % (sys.argv[0], git_repository, git_folder))
            print('  python %s %s %s zendesk' % (sys.argv[0], git_repository, git_folder))
        else:
            print('  python %s %s %s upload' % (sys.argv[0], git_repository, git_folder))
            print('  python %s %s %s download' % (sys.argv[0], git_repository, git_folder))

            if repository.github.upstream == 'liferay/liferay-learn':
                print('  python %s %s %s disclaimer' % (sys.argv[0], git_repository, git_folder))

def execute_job(domain, git_repository, git_folder, direction):
    all_repositories = get_repositories(False)

    check_repositories = []

    for repository in all_repositories:
        if repository is None:
            continue

        git_root = repository.github.git_root

        if git_root[git_root.rfind('/')+1:] != git_repository:
            continue

        if repository.github.single_folder is None:
            if repository.github.project_folder != git_folder:
                continue
        else:
            if repository.github.single_folder != git_folder:
                continue

        check_repositories.append(repository)

    if len(check_repositories) != 1:
        list_jobs()
        return

    repository = check_repositories[0]

    if repository.github.origin == 'holatuwol/zendesk-articles':
        if direction == 'crowdin':
            copy_zendesk_to_crowdin(repository, domain, 'ja')
        elif direction == 'zendesk':
            copy_crowdin_to_zendesk(repository, domain, 'ja')
        else:
            print('invalid target of zendesk sync (crowdin, zendesk)')
    elif repository.github.upstream == 'liferay/liferay-learn':
        print(repository)

        if direction == 'upload':
            copy_learn_to_crowdin(repository, 'ja')
        elif direction == 'download':
            copy_crowdin_to_learn(repository, 'ja')
        elif direction == 'disclaimer':
            add_disclaimers_to_learn(repository, 'ja')
        else:
            print('invalid target of learn sync (upload, download, disclaimer)')
    else:
        if direction == 'upload':
            sync_sources = True
        elif direction == 'download':
            sync_sources = False
        else:
            print('invalid target of crowdin sync (upload, download)')

        print(repository)

        value = input('continue (y/n): ')

        if value == 'y':
            update_repository(repository, sync_sources=sync_sources)

if __name__ == '__main__':
    if len(sys.argv) < 4:
        list_jobs()
    else:
        execute_job(prod_domain, sys.argv[1], sys.argv[2], sys.argv[3])