from crowdin_sync import update_repository
from crowdin_util import crowdin_request
import json
import os
import pandas as pd
from repository import get_repository, initial_dir
import sys
import time
from zendesk.zendesk import copy_crowdin_to_zendesk, copy_zendesk_to_crowdin, download_zendesk_articles, fix_author_source_locale, translate_zendesk_on_crowdin

uat_domain = 'liferaysupport1528999723.zendesk.com'
prod_domain = 'liferay-support.zendesk.com'

def get_repositories():
    projects = []

    repositories_df = pd.read_csv('%s/repositories.csv' % initial_dir, comment='#')

    for project_id in repositories_df['project_id'].unique():
        status_code, response_data = crowdin_request('/projects/%s' % project_id, 'GET')
        projects.append(response_data)

    repositories = [get_repository(projects, **x) for x in repositories_df.to_dict('records')]

    return repositories

def list_jobs():
    all_repositories = get_repositories()

    print()
    print('Valid commands:')

    def print_zendesk_help(git_repository, target_language):
        print('  python %s %s crowdin %s' % (sys.argv[0], git_repository, target_language))
        print('  python %s %s translate %s' % (sys.argv[0], git_repository, target_language))
        print('  python %s %s update %s' % (sys.argv[0], git_repository, target_language))
        print('  python %s %s zendesk %s' % (sys.argv[0], git_repository, target_language))

    for repository in all_repositories:
        if repository is None:
            continue

        git_root = repository.github.git_root

        git_repository = git_root[git_root.rfind('/')+1:]

        if repository.github.origin == 'holatuwol/zendesk-articles':
            for target_language in ['ja', 'ko']:
                print_zendesk_help(git_repository, target_language)
        elif repository.github.origin == 'holatuwol/zendesk-articles-ja':
            print_zendesk_help(git_repository, 'en-us')
        else:
            for target_language in ['ja', 'ko']:
                print('  python %s %s upload %s' % (sys.argv[0], git_repository, target_language))
                print('  python %s %s download %s' % (sys.argv[0], git_repository, target_language))

            if repository.github.upstream == 'liferay/liferay-learn':
                print('  python %s %s disclaimer %s' % (sys.argv[0], git_repository, target_language))

def execute_job(domain, git_repository, direction, target_language):
    all_repositories = get_repositories()

    check_repositories = []

    for repository in all_repositories:
        if repository is None:
            continue

        git_root = repository.github.git_root

        if git_root[git_root.rfind('/')+1:] != git_repository:
            continue

        check_repositories.append(repository)

    if len(check_repositories) != 1:
        list_jobs()
        return

    repository = check_repositories[0]

    if repository.github.origin == 'holatuwol/zendesk-articles':
        if direction == 'crowdin':
            copy_zendesk_to_crowdin(repository, domain, 'en-us', target_language)
        elif direction == 'translate':
            translate_zendesk_on_crowdin(repository, domain, 'en-us', target_language)
        elif direction == 'update':
            download_zendesk_articles(repository, domain, 'en-us', target_language, True)
        elif direction == 'zendesk':
            copy_crowdin_to_zendesk(repository, domain, 'en-us', target_language)
        else:
            print('invalid target of zendesk sync (crowdin, translate, update, zendesk)')
    elif repository.github.origin == 'holatuwol/zendesk-articles-ja':
        if direction == 'crowdin':
            copy_zendesk_to_crowdin(repository, domain, 'ja', 'en-us')
        elif direction == 'translate':
            translate_zendesk_on_crowdin(repository, domain, 'ja', 'en-us')
        elif direction == 'update':
            download_zendesk_articles(repository, domain, 'ja', 'en-us', True)
        elif direction == 'zendesk':
            with open('authors_ja.json', 'r') as f:
                authors = json.load(f)

            copy_crowdin_to_zendesk(repository, domain, 'ja', 'en-us', authors)
        else:
            print('invalid target of zendesk sync (crowdin, zendesk)')
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

def fix_locale(domain, git_repository, bad_language, good_language, author_id):
    all_repositories = get_repositories()

    check_repositories = []

    for repository in all_repositories:
        if repository is None:
            continue

        git_root = repository.github.git_root

        if git_root[git_root.rfind('/')+1:] != git_repository:
            continue

        check_repositories.append(repository)

    if len(check_repositories) != 1:
        list_jobs()
        return

    repository = check_repositories[0]

    fix_author_source_locale(repository, domain, bad_language, good_language, author_id)

if __name__ == '__main__':
    print(sys.argv)
    if len(sys.argv) < 4:
        list_jobs()
    elif sys.argv[2] == 'locale':
        fix_locale(prod_domain, sys.argv[1], sys.argv[3], sys.argv[4], int(sys.argv[5]))
    else:
        execute_job(prod_domain, sys.argv[1], sys.argv[2], sys.argv[3])
