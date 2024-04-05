#! python3
import json
import requests
import pywikibot
import mwparserfromhell
import re
import os
from datetime import datetime
from qwikidata.sparql import return_sparql_query_results

scriptDir = os.path.dirname(os.path.abspath(__file__))
versionResponse = requests.get('https://apiv3.iucnredlist.org/api/v3/version')
versionResponse.raise_for_status()
redListEdition = versionResponse.json()['version']

with open('credentials.json') as f:
    credentials = json.load(f)

def fetchWikidata():
    sparql = '''
    SELECT DISTINCT ?page_titleES ?iucn
    WHERE {
        ?item wdt:P627 ?iucn .
        ?article schema:about ?item ;
        schema:isPartOf <https://es.wikipedia.org/> ;
        schema:name ?page_titleES .
    }
    '''

    return return_sparql_query_results(sparql)['results']['bindings']

def getSpeciesData(id, title):
    iucnToken = credentials['iucnToken']
    url = 'https://apiv3.iucnredlist.org/api/v3/species/id/%s?token=%s' % (id, iucnToken)

    response = requests.get(url)
    response.raise_for_status()
    try:
        speciesData = response.json()['result'][0]
    except IndexError:
        # attempt to get data from scientific name
        try:
            url = 'https://apiv3.iucnredlist.org/api/v3/species/%s?token=%s' % (title, iucnToken)

            response = requests.get(url)
            response.raise_for_status()
            speciesData = response.json()['result'][0]
            itemToFix = {
                'name': title,
                'id': id,
                'correctId': str(speciesData['taxonid'])
            }
            relPath = 'data/idstofix.json'
            absFilePath = os.path.join(scriptDir, relPath)  
            with open(absFilePath, 'a', encoding='utf8') as idsToFix:
                json.dump(itemToFix, idsToFix, ensure_ascii=False, indent=4)
        except:
            speciesData
            return speciesData

    return speciesData

def editWikipedia(fullText, iucnInfo):
    statusRefIsNamedReference = False
    parsedWikitext = mwparserfromhell.parse(fullText)
    for template in parsedWikitext.filter_templates():
        if  template.name.matches('IUCN') and template.has('año') and ( \
            (iucnInfo['assessment_date'][:4] in template.get('año').value) or \
            (iucnInfo['published_year'] in template.get('año').value) ):
            return # Do nothing if last assessment date is the same as in the infobox reference, as it's up to date
    for template in parsedWikitext.filter_templates():
        if template.name.matches('Ficha de taxón'):
            if template.has('status'):
                template.remove('status')
            if template.has('status_system'):
                template.remove('status_system')
            if template.has('status_ref'):
                statusRef = template.get('status_ref')

                # If there's a named reference in the status_ref parameter, substitute it later in the text to avoid errors
                namedReference = re.search(r'<ref name\s*=\s*"?(.*?)"?>.*?<\/ref>', str(statusRef))
                if namedReference:
                    fullReference = namedReference.group(0)
                    referenceId = namedReference.group(1)
                    statusRefIsNamedReference = True

                template.remove('status_ref')

            template.add('status', iucnInfo['category'])
            template.add('status_system', 'iucn3.1')
            template.add('status_ref', '<ref>{{IUCN|título=' + iucnInfo['scientific_name']
                            + '|asesores=' + iucnInfo['assessor']
                            + '|año=' + iucnInfo['assessment_date'][:4]
                            + '|edición=' + redListEdition
                            + '|consultado=' + datetime.today().strftime('%Y-%m-%d')
                            + '}}</ref>')
                
    finalText = str(parsedWikitext)
    if statusRefIsNamedReference:
        # Replace the reference that was in the taxobox wherever it's used again, once.
        pattern = r'<ref name\s*=\s*"?' + referenceId + r'"?\s*\/\s*>'
        finalText = re.sub(pattern, fullReference, finalText, count=1)

    return finalText

def main():
    sparqlResult = fetchWikidata()
    relPath = 'data/data.json'
    absFilePath = os.path.join(scriptDir, relPath)  
    with open(absFilePath, 'w+', encoding='utf8') as wikidata:
        json.dump(sparqlResult, wikidata, ensure_ascii=False, indent=4)
    site = pywikibot.Site('es', 'wikipedia')
    for entry in sparqlResult:
        page = pywikibot.Page(site, entry['page_titleES']['value'])
        if not page:
            continue
        fullText = page.text
        iucnInfo = getSpeciesData(entry['iucn']['value'], entry['page_titleES']['value'])
        if not iucnInfo:
            continue
        finalText = editWikipedia(fullText, iucnInfo)
        if not finalText:
            continue
        page.text = finalText
        page.save(summary='Bot: actualizando [[Lista Roja de la UICN]]', minor=False)

main()