from crowdin_sync import update_repository
from github import is_repository_accessible
import os
import pandas as pd
from repository import get_repository, initial_dir
from zendesk import update_zendesk_articles

def recheck_code_translations(repository, update_result):
    new_files, all_files, file_info = update_result

    os.chdir(repository.github.git_root)

    for folder in get_root_folders(repository, all_files):
        pre_translate_folder(repository, folder, all_files, file_info)

    code_file_count = 0

    for file in all_files:
        if delete_code_translations(repository, file, file_info):
            code_file_count = code_file_count + 1
    
    logging.info('%d files needed code deletions' % code_file_count)

    crowdin_download_translations(repository, all_files, all_files, file_info)

    os.chdir(initial_dir)

def get_repositories(check_accessible=True):
    os.chdir(initial_dir)
    repositories_df = pd.read_csv('repositories.csv', comment='#')
    repositories_df.fillna('', inplace=True)

    repositories = [get_repository(**x) for x in repositories_df.to_dict('records')]

    if check_accessible:
        for git_repository, crowdin_repository in repositories:
            assert(is_repository_accessible(git_repository.origin))
            assert(is_repository_accessible(git_repository.upstream))

    return repositories

def run_cronjob():
    os.chdir(initial_dir)

    uat_domain = 'liferaysupport1528999723.zendesk.com'
    prod_domain = 'liferay-support.zendesk.com'

    repositories = get_repositories()

    for repository in repositories:
        if repository.crowdin.dest_folder.find('zendesk') == 0:
            update_zendesk_articles(repository, uat_domain)

    for repository in repositories:
        if repository.crowdin.dest_folder.find('zendesk') == -1:
            update_result = update_repository(repository)

if __name__ == '__main__':
    run_cronjob()