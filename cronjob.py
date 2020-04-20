from crowdin import delete_translation_folder
from github import is_repository_accessible
import os
import pandas as pd
from repository import get_repository, initial_dir
import time
from zendesk import update_zendesk_articles

uat_domain = 'liferaysupport1528999723.zendesk.com'
prod_domain = 'liferay-support.zendesk.com'

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

def zendesk_cronjob(domain):
    os.chdir(initial_dir)

    repositories = get_repositories(False)[0:3]

    for repository in repositories:
        assert(repository.github.origin == 'holatuwol/zendesk-articles')

    while True:
        try:
            zendesk_articles = update_zendesk_articles(repositories, domain)
            break
        except:
            time.sleep(60)
            pass

    for repository in repositories:
        delete_translation_folder(repository)

if __name__ == '__main__':
    zendesk_cronjob(prod_domain)