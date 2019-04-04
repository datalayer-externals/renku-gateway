# -*- coding: utf-8 -*-
#
# Copyright 2018-2019 - Swiss Data Science Center (SDSC)
# A partnership between École Polytechnique Fédérale de Lausanne (EPFL) and
# Eidgenössische Technische Hochschule Zürich (ETHZ).
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
"""Graph endpoint."""

from quart import Blueprint, current_app, jsonify, request
from SPARQLWrapper import DIGEST, JSON, POST, SPARQLWrapper

blueprint = Blueprint('graph', __name__, url_prefix='/graph')

LINEAGE_GLOBAL = """
PREFIX prov: <http://www.w3.org/ns/prov#>
PREFIX rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#>
PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>
PREFIX wfdesc: <http://purl.org/wf4ever/wfdesc#>
PREFIX wf: <http://www.w3.org/2005/01/wf/flow#>
PREFIX wfprov: <http://purl.org/wf4ever/wfprov#>
PREFIX foaf: <http://xmlns.com/foaf/0.1/>
PREFIX dcterms: <http://purl.org/dc/terms/>

SELECT ?target ?source ?target_label ?source_label
WHERE {{
  {{
    SELECT ?entity
    WHERE {{
      {filter}
      ?qentity (
        ^(prov:qualifiedGeneration/prov:activity/prov:qualifiedUsage/prov:entity)* |
        (prov:qualifiedGeneration/prov:activity/prov:qualifiedUsage/prov:entity)*
      ) ?entity .
    }}
    GROUP BY ?entity
  }}
  {{
    ?entity prov:qualifiedGeneration/prov:activity ?activity ;
            rdfs:label ?target_label .
    ?activity rdfs:comment ?source_label .
    FILTER NOT EXISTS {{?activity rdf:type wfprov:WorkflowRun}}
    FILTER EXISTS {{?activity rdf:type wfprov:ProcessRun}}
    BIND (?entity AS ?target)
    BIND (?activity AS ?source)
  }} UNION {{
    ?activity prov:qualifiedUsage/prov:entity ?entity ;
              rdfs:comment ?target_label .
    ?entity rdfs:label ?source_label .
    FILTER NOT EXISTS {{?activity rdf:type wfprov:WorkflowRun}}
    FILTER EXISTS {{?activity rdf:type wfprov:ProcessRun}}
    BIND (?activity AS ?target)
    BIND (?entity AS ?source)
  }}
}}
"""


@blueprint.route('/<namespace>/<project>/lineage')
@blueprint.route('/<namespace>/<project>/lineage/<commit_ish>')
@blueprint.route('/<namespace>/<project>/lineage/<commit_ish>/<path:path>')
async def lineage(namespace, project, commit_ish=None, path=None):
    """Query graph service."""
    gitlab_url = current_app.config['GITLAB_URL']
    if gitlab_url.endswith('/gitlab'):
        gitlab_url = gitlab_url[:-len('/gitlab')]
    central_node = None
    project_url = '{gitlab}/{namespace}/{project}'.format(
        gitlab=gitlab_url,
        namespace=namespace,
        project=project,
    )

    sparql = SPARQLWrapper(current_app.config['SPARQL_ENDPOINT'])

    # SPARQLWrapper2 for JSON

    sparql.setHTTPAuth(DIGEST)
    sparql.setCredentials(
        current_app.config['SPARQL_USERNAME'],
        current_app.config['SPARQL_PASSWORD'],
    )
    sparql.setReturnFormat(JSON)
    sparql.setMethod(POST)

    filter = [
        '?qentity dcterms:isPartOf ?project .',
        # TODO filter entities from private projects
        'FILTER (?project = <{project_url}>)'.format(project_url=project_url),
    ]
    if commit_ish:
        filter.extend([
            '?qentity (prov:qualifiedGeneration/prov:activity | '
            '^prov:entity/^prov:qualifiedUsage) ?qactivity .',
            'FILTER (?qactivity = <file:///commit/{commit_ish}>)'.format(
                commit_ish=commit_ish
            ),
        ])

    if path:
        central_node = 'file:///blob/{commit_ish}/{path}'.format(
            commit_ish=commit_ish,
            path=path,
        )
        filter.append(
            'FILTER (?qentity = <{central_node}>)'.format(
                central_node=central_node
            ),
        )

    query = LINEAGE_GLOBAL.format(filter='\n          '.join(filter))

    sparql.setQuery(query)
    results = sparql.query().convert()

    nodes = {}
    edges = []

    for item in results['results']['bindings']:
        nodes[item['source']['value']] = {
            'id': item['source']['value'],
            'label': item['source_label']['value']
        }
        nodes[item['target']['value']] = {
            'id': item['target']['value'],
            'label': item['target_label']['value']
        }
        edges.append({key: item[key]['value'] for key in ('source', 'target')})

    # TODO: Maybe this logic can be integrated in the SPARQL query itself?
    nodes_list = list(nodes.values())
    renku_cli_nodes = [node for node in nodes_list
                       if node['label'].startswith('renku')]

    for node in renku_cli_nodes:
        edges_target = [edge for edge in edges if edge['target'] == node['id']]
        edges_source = [edge for edge in edges if edge['source'] == node['id']]
        if len(edges_target) == 1 and len(edges_source) == 0:
            edges.remove(edges_target[0])
            nodes_list.remove(node)
        elif len(edges_target) == 0 and len(edges_source) == 1:
            edges.remove(edges_source[0])
            nodes_list.remove(node)

    return jsonify({
        'nodes': nodes_list,
        'edges': edges,
    })
