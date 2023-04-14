from collections import namedtuple
from inspect import getsourcefile
import git
import logging
import os

initial_dir = os.path.dirname(os.path.abspath(getsourcefile(lambda:0)))

GitHubRepository = namedtuple(
    'GitHubRepository',
    ' '.join(['git_root', 'origin', 'upstream', 'branch', 'project_folder', 'single_folder'])
)

CrowdInRepository = namedtuple(
    'CrowdinRepository',
    ' '.join(['source_language', 'project_id', 'project_name', 'api_key', 'dest_folder', 'delete_enabled', 'single_folder'])
)

TranslationRepository = namedtuple(
    'TranslationRepository',
    ' '.join(['github', 'crowdin'])
)

def get_repository(projects, source_language, git_repository, git_branch, git_folder, project_id, project_name, project_folder, single_folder, delete_enabled):
    single_folder = single_folder.strip()

    if len(single_folder) == 0:
        github_single_folder = None
        crowdin_single_folder = project_folder
    else:
        github_single_folder = git_folder + '/' + single_folder
        crowdin_single_folder = project_folder + '/' + single_folder
    
    git_root = os.path.dirname(initial_dir) + '/' + git_repository

    if not os.path.isdir(git_root):
        return None

    os.chdir(git_root)

    logging.info(git_root)

    origin_url = git.remote('get-url', 'origin')

    if origin_url.find('https://') == 0:
        origin = origin_url[origin_url.find('/', 8)+1:origin_url.rfind('.')]
    else:
        origin = origin_url.split(':')[1][:-4]

    upstream_url = git.remote('get-url', 'upstream')

    if len(upstream_url) == 0:
        upstream = None
    elif upstream_url.find('https://') == 0:
        upstream = upstream_url[upstream_url.find('/', 8)+1:upstream_url.rfind('.')]
        print(upstream)
    else:
        upstream = upstream_url.split(':')[1][:-4]

    project_api_keys = [project['key'] if 'key' in project else None for project in projects if project['identifier'] == project_name]

    if len(project_api_keys) == 0:
        project_api_key = None
    else:
        project_api_key = project_api_keys[0]

    os.chdir(initial_dir)

    return TranslationRepository(
        GitHubRepository(git_root, origin, upstream, git_branch, git_folder, github_single_folder),
        CrowdInRepository(source_language, project_id, project_name, project_api_key, project_folder, delete_enabled, crowdin_single_folder)
    )

def get_subrepositories(repository):
    github = repository.github
    crowdin = repository.crowdin

    base_folder = '%s/%s' % (github.git_root, github.single_folder)

    return [
        TranslationRepository(
            GitHubRepository(github.git_root, github.origin, github.upstream, github.branch, github.project_folder, '%s/%s' % (github.single_folder, sub_folder)),
            CrowdInRepository(crowdin.project_id, crowdin.project_name, crowdin.api_key, crowdin.dest_folder, crowdin.delete_enabled, '%s/%s' % (crowdin.single_folder, sub_folder))
        )
        for sub_folder in sorted(os.listdir(base_folder))
    ]
