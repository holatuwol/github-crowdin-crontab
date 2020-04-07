from crowdin import _pandoc
from file_manager import get_crowdin_file, get_eligible_files
import git
import os
from repository import initial_dir
from zendesk import add_category_articles, download_zendesk_articles, get_zendesk_articles, zendesk_get_request

def get_title(file):
    with open(file, 'r') as f:
        for line in f.readlines():
            if line.find('#') == 0:
                return line[1:].strip()

    return None

def add_mt_disclaimers(repository, file_info):
    disclaimer_text = '''
<p class="alert alert-info"><span class="wysiwyg-color-blue120">
ファストトラック記事は、お客様の利便性のために一部機械翻訳されています。また、ドキュメントは頻繁に更新が加えられており、翻訳は未完成の部分が含まれることをご了承ください。最新情報は都度公開されておりますため、必ず英語版をご参照ください。翻訳に問題がある場合は、<a href="mailto:support-content-jp@liferay.com">こちら</a>までご連絡ください。
</span></p>
'''

    os.chdir(repository.github.git_root)

    root_folder = repository.github.single_folder \
        if repository.github.single_folder is not None else repository.github.project_folder

    titles = {}

    for file in get_eligible_files(repository, git.ls_files(root_folder), 'en'):
        crowdin_file = get_crowdin_file(repository, file)

        target_file = 'ja/' + file[3:] if file[0:3] == 'en/' else file.replace('/en/', '/ja/')

        if not os.path.isfile('%s/%s' % (repository.github.git_root, target_file)):
            if target_file[-9:] == '.markdown':
                target_file = target_file[:-9] + '.md'
            elif target_file[-3:] == '.md':
                target_file = target_file[:-3] + '.markdown'

            if not os.path.isfile('%s/%s' % (repository.github.git_root, target_file)):
                continue

        html_file = target_file[:target_file.rfind('.')] + '.html'
        titles[html_file] = get_title(file)

        _pandoc(target_file, html_file, '--from=gfm', '--to=html')

        if crowdin_file in file_info and file_info[crowdin_file]['translated'] == file_info[crowdin_file]['approved']:
            continue

        with open(html_file, 'r') as f:
            lines = f.readlines()

            content = '%s%s\n%s' % (lines[0], disclaimer_text, ''.join(lines[1:]))

        with open(html_file, 'w') as f:
            f.write(content)

    os.chdir(initial_dir)

    return titles

forced_matches = {
    'ja/develop/tutorials/articles/04-developing-a-web-application/03-generating-the-backend/01-what-is-service-builder.html': '360018164091',
    'ja/develop/tutorials/articles/04-developing-a-web-application/08-search-and-indexing/01-enabling-search-and-indexing-for-guestbooks/05-summarizing-search-documents.html': '360020485692',
    'ja/develop/tutorials/articles/04-developing-a-web-application/08-search-and-indexing/02-enabling-search-and-indexing-for-guestbook-entries/04-summarizing-search-documents.html': '360020754251',
    'ja/develop/tutorials/articles/130-service-builder/01-what-is-service-builder.html': '360017886532',
    'ja/develop/tutorials/articles/220-mobile/01-android-apps-with-liferay-screens/07-creating-android-screenlets/02-screenlet-interactor.html': '360020189352',
    'ja/develop/tutorials/articles/220-mobile/01-android-apps-with-liferay-screens/07-creating-android-screenlets/04-screenlet-class.html': '360020189392',
    'ja/develop/tutorials/articles/220-mobile/01-android-apps-with-liferay-screens/08-creating-android-list-screenlets/03-list-screenlet-interactor.html': '360020446791',
    'ja/develop/tutorials/articles/220-mobile/01-android-apps-with-liferay-screens/08-creating-android-list-screenlets/04-list-screenlet-class.html': '360020446811'
}

def get_title_matches(markdown_title, category_articles):
    matches = []

    base_title = markdown_title.replace('@product@', 'Liferay DXP').replace('@ide@', 'Dev Studio')

    check_title = base_title.replace('@product-ver@', '7.1')

    for key, value in category_articles.items():
        if check_title == value['name'] and 'DXP 7.1' in value['label_names']:
            matches.append(key)

    if len(matches) != 0:
        return matches

    check_title = base_title.replace('@product-ver@', 'Liferay DXP 7.1')

    for key, value in category_articles.items():
        if check_title == value['name'] and 'DXP 7.1' in value['label_names']:
            matches.append(key)

    if len(matches) != 0:
        return matches

    check_title = base_title.replace('Dev Studio', 'Dev Studio DXP')

    for key, value in category_articles.items():
        if check_title == value['name'] and 'DXP 7.1' in value['label_names']:
            matches.append(key)

    return matches

def get_article_id(file, title, category_articles):
    if file in forced_matches:
        return forced_matches[file]

    matches = get_title_matches(title, category_articles)

    if len(matches) == 0:
        matches = get_title_matches('Introduction to ' + title, category_articles)

    if len(matches) == 1:
        return matches[0]

    return None

def get_translation_target_articles(domain, repository, file_info):
    titles = add_mt_disclaimers(repository, file_info)

    categories = zendesk_get_request(domain, '/help_center/en-us/categories.json', 'categories')
    sections = zendesk_get_request(domain, '/help_center/en-us/sections.json', 'sections')
    articles = download_zendesk_articles(repository, domain)

    article_paths = {}

    add_category_articles(articles, categories, 'Liferay DXP 7.1 Developer Tutorials', sections, article_paths)

    category_article_ids = set(article_paths.keys())

    category_articles = {
        key: value for key, value in articles.items() if key in category_article_ids
    }

    article_ids = {
        key: get_article_id(key, value, category_articles)
            for key, value in titles.items()
    }

    return article_ids, articles