To get a list of available ways to run this script:

```py
python cronjob.py
```

Download and install the older version of the Crowdin CLI.

https://github.com/crowdin/crowdin-cli/tree/v2.0.31

Also download and install pandoc.

https://pandoc.org/installing.html

Set a bunch of Crowdin credentials as git configuration values.

```
git config --global crowdin.login EMAIL_ADDRESS       # https://crowdin.com/settings#account "Email"
git config --global crowdin.password PASSWORD         # https://crowdin.com/settings#password "Password"
git config --global crowdin.account-login LOGIN       # https://crowdin.com/settings#account "Username"
git config --global crowdin.account-key-v1 V1_KEY     # https://crowdin.com/settings#api-key "Account API key"
git config --global crowdin.account-key-v2 V2_KEY     # https://crowdin.com/settings#api-key "Personal Access Tokens"
```

Also set Zendesk OAuth token.

```
git config --global liferay-support.zendesk.com.token HELLO_TOKEN
```

## Running through conda

https://docs.conda.io/en/latest/miniconda.html

```
conda install -y bs4 numpy pandas requests tqdm
```

## Running through docker