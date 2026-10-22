# Alexa Interaction Models

This directory holds the interaction model of the skill, one file per locale:

| File | Language                 |
|------|--------------------------|
| de-DE.json | German (Germany)         |
| en-US.json | English (United States)  |
| es-ES.json | Spanish (Spain)          |
| fr-FR.json | French (France)          |
| it-IT.json | Italian (Italy)          |
| pt-BR.json | Portuguese (Brazil)      |

Every file is a complete interaction model in the format that the Alexa
Developer Console expects, so that its contents can be pasted into the JSON
editor of the console as they are.

## Upload a model

1. *Interaction Model* → *Add Language* → the language of the file.
2. Copy the contents of the file into the JSON editor and click *Save Model*.

The invocation name is "zero mukke" in every locale, so that the voice
commands of the media renderers work with the configured
`NAVI_ALEXA_SKILL_NAME`.

## Change a model

Edit the file of the locale that is changed and upload it in the console
again.  There is no generated file that has to be kept in sync.

A new locale is added by copying an existing file, translating it and adding
the locale to `SUPPORTED_LOCALES` in `skill/castnavidrome/localization.py`.
