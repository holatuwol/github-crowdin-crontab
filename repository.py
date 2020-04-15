from collections import namedtuple
import git
import logging
import os

initial_dir = os.getcwd()

GitHubRepository = namedtuple(
    'GitHubRepository',
    ' '.join(['git_root', 'origin', 'upstream', 'branch', 'project_folder', 'single_folder'])
)

CrowdInRepository = namedtuple(
    'CrowdinRepository',
    ' '.join(['project_id', 'project_name', 'api_key', 'dest_folder', 'delete_enabled'])
)

TranslationRepository = namedtuple(
    'TranslationRepository',
    ' '.join(['github', 'crowdin'])
)

def get_repository(git_repository, git_branch, git_folder, project_id, project_name, project_folder, single_folder, delete_enabled):
    single_folder = single_folder.strip()

    if len(single_folder) == 0:
        single_folder = None
    else:
        single_folder = git_folder + '/' + single_folder
    
    git_root = os.path.dirname(initial_dir) + '/' + git_repository

    os.chdir(git_root)

    logging.info(git_root)

    origin_url = git.remote('get-url', 'origin')
    origin = origin_url.split(':')[1][:-4]

    upstream_url = git.remote('get-url', 'upstream')
    
    if len(upstream_url) == 0:
        upstream = None
    else:
        upstream = upstream_url.split(':')[1][:-4]

    project_api_key = git.config('crowdin.api-key.%s' % project_name)

    os.chdir(initial_dir)

    return TranslationRepository(
        GitHubRepository(git_root, origin, upstream, git_branch, git_folder, single_folder),
        CrowdInRepository(project_id, project_name, project_api_key, project_folder, delete_enabled)
    )

def get_subrepositories(repository):
    github = repository.github
    base_folder = '%s/%s' % (github.git_root, github.single_folder)

    return [
        TranslationRepository(
            GitHubRepository(github.git_root, github.origin, github.upstream, github.branch, github.project_folder, '%s/%s' % (github.single_folder, sub_folder)),
            repository.crowdin
        )
        for sub_folder in sorted(os.listdir(base_folder))
    ]
