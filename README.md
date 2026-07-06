## Script prerequisites

Install `uv` following the instructions at https://docs.astral.sh/uv/#projects

```
uv venv
uv pip install -r requirements.txt
```

## Translation process

### Sync state between local and learn.liferay.com
```
./translate_learn.sh copy_crowdin_to_local
./translate_learn.sh copy_local_to_learn
./translate_learn.sh copy_learn_to_local
./translate_learn.sh check_outdated_articles
```

### Translate the next batch

```
./translate_learn.sh copy_local_to_crowdin
```

https://crowdin.com/project/liferay-japan-documentation
* Auto-Translate
  * Auto-Translation via: Translation Memory
  * Minimum match ratio: Perfect
  * Target languages: Japanese
  * Scope: Untranslated strings
  * Files: learn.liferay.com

https://crowdin.com/project/liferay-japan-documentation
* Auto-Translate
  * Auto-Translation via: Machine Translation
  * Translation engine: Google Translate
  * Target languages: Japanese
  * Scope: Untranslated strings
  * Files: learn.liferay.com

https://crowdin.com/project/liferay-japan-documentation/tools/pre-translation-queue
* Wait until completion

https://crowdin.com/project/liferay-japan-documentation
* Auto-Translate
  * Auto-Translation via: Machine Translation
  * Translation engine: DeepL Translator
  * Target languages: Japanese
  * Scope: Untranslated strings
  * Files: learn.liferay.com

https://crowdin.com/project/liferay-japan-documentation/tools/pre-translation-queue
* Wait until completion

https://crowdin.com/project/liferay-japan-documentation/ja
* Manually translate anything that failed to translate

### Sync state between local and learn.liferay.com again
```
./translate_learn.sh copy_crowdin_to_local
./translate_learn.sh copy_local_to_learn
./translate_learn.sh copy_learn_to_local
./translate_learn.sh check_outdated_articles
```
