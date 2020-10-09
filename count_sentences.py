from bs4 import BeautifulSoup
import json
import pandas as pd
import nltk
#nltk.download('punkt')
from nltk.tokenize import sent_tokenize

with open('all_articles_liferay-support.zendesk.com.json', 'r') as f:
    articles = json.load(f)

with open('sections_liferay-support.zendesk.com.json', 'r') as f:
    sections = json.load(f)

with open('categories_liferay-support.zendesk.com.json', 'r') as f:
    categories = json.load(f)

category_df = pd.DataFrame(categories.values())[['id', 'name']]
section_df = category_df.merge(
	pd.DataFrame(sections.values())[['id', 'category_id', 'name']],
	how='left', left_on='id', right_on='category_id', suffixes=['_category', '_section']
)

article_df = section_df.merge(
	pd.DataFrame(articles.values())[['id','section_id','body','source_locale']],
	how='right', left_on='id_section', right_on='section_id', suffixes=['_section', '']
)

def count_sentences(body):
    if body is None:
        return 0
    soup = BeautifulSoup(body, 'html.parser')
    return len(sent_tokenize(soup.text))

article_df['sentence_count'] = article_df['body'].apply(count_sentences)

article_df[['id', 'category_id', 'name_category', 'section_id', 'name_section', 'sentence_count']].to_csv('count_sentences.csv')