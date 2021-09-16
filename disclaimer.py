disclaimer_zendesk = {
'ja': '''
<aside class="alert alert-info"><span class="wysiwyg-color-blue120">
ご覧のページは、お客様の利便性のために一部機械翻訳されています。また、ドキュメントは頻繁に更新が加えられており、翻訳は未完成の部分が含まれることをご了承ください。最新情報は都度公開されておりますため、必ず英語版をご参照ください。翻訳に問題がある場合は、<a href="mailto:support-content-jp@liferay.com">こちら</a>までご連絡ください。
</span></aside>
''',
'en-us': '''
<aside class="alert alert-info"><span class="wysiwyg-color-blue120">
This article has been machine translated from its original language for your convenience.  Please use discretion as this translation may include some inaccuracies. If you encounter issues with the translation, please use the feedback button to let us know.
</span></aside>
'''
}

disclaimer_zendesk_no_newline = {
    key: value.replace('\n', '').strip() for key, value in disclaimer_zendesk.items()
}

disclaimer_learn = {
'ja': '''
``` note::
   ご覧のページは、お客様の利便性のために一部機械翻訳されています。また、ドキュメントは頻繁に更新が加えられており、翻訳は未完成の部分が含まれることをご了承ください。最新情報は都度公開されておりますため、必ず英語版をご参照ください。翻訳に問題がある場合は、 [こちら](mailto:support-content-jp@liferay.com) までご連絡ください。
```
'''
}

def add_disclaimer_learn(file, language):
    with open(file, 'r') as f:
        lines = f.readlines()

    start_pos = 2

    if lines[1].find('==') == 0:
        start_pos = 3

    new_title = ''.join(lines[0:start_pos]).strip()
    old_content = ''.join(lines[start_pos:]).strip()

    if lines[start_pos].strip() == '``` note::':
        new_content = disclaimer_learn[language] + '\n' + ''.join(lines[start_pos+3:]).strip()
    else:
        new_content = disclaimer_learn[language] + '\n' + ''.join(lines[start_pos:]).strip()

    return new_title, old_content, new_content

def add_disclaimer_zendesk(article, file, language):
    with open(file, 'r') as f:
        lines = f.readlines()

    new_title = lines[0][4:-6]
    old_content = ''.join(lines[1:]).strip()

    if lines[1].strip() == '<p class="alert alert-info"><span class="wysiwyg-color-blue120">':
        new_content = ''.join(lines[4:]).strip()
    if lines[1].strip() == '<aside class="alert alert-info"><span class="wysiwyg-color-blue120">':
        new_content = ''.join(lines[4:]).strip()
    elif len(lines) > 2 and lines[2].strip() == '<p class="alert alert-info"><span class="wysiwyg-color-blue120">':
        new_content = ''.join(lines[5:]).strip()
    elif len(lines) > 2 and lines[2].strip() == '<aside class="alert alert-info"><span class="wysiwyg-color-blue120">':
        new_content = ''.join(lines[5:]).strip()
    else:
        new_content = ''.join(lines[1:]).strip()

    if new_content.find('<aside class="alert alert-info"><span class="wysiwyg-color-blue120">') != -1:
        new_content = new_content[new_content.find('</span></aside>')+15:].strip()

    script_disclaimer = new_content.find('var disclaimerElement')

    if script_disclaimer != -1:
        script_disclaimer = new_content.rfind('<script>', 0, script_disclaimer)
        new_content = new_content[0:script_disclaimer].strip()

    if 'mt' in article['label_names'] and language is not None and language != 'en':
        new_content = (disclaimer_zendesk[language] + new_content).strip()

    return new_title, old_content, new_content