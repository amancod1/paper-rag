import time
import requests
from datetime import datetime
from fastapi import Depends
from fastapi import APIRouter
from fastapi import HTTPException

from danswer.server.papers.paper_api import ArxivAPI
from danswer.server.documents.models import (
    ConnectorBase,
    CredentialBase,
    ConnectorCredentialPairMetadata,
    RunConnectorRequest,
    ConnectorCredentialPairIdentifier,
    ConnectorIndexingStatus,
    ConnectorSnapshot,
    CredentialSnapshot,
    IndexAttemptSnapshot
)
from danswer.db.document import get_document_cnts_for_cc_pairs
from danswer.db.engine import get_sqlalchemy_engine
from danswer.db.connector import create_connector, get_connector_credential_ids
from danswer.db.credentials import create_credential
from danswer.db.connector_credential_pair import add_credential_to_connector, get_connector_credential_pairs
from danswer.db.index_attempt import get_index_attempts_for_cc_pair, create_index_attempt, get_latest_index_attempts
from danswer.db.embedding_model import get_current_db_embedding_model
from danswer.background.celery.celery_utils import get_deletion_status
from danswer.db.deletion_attempt import check_deletion_attempt_is_allowed
from danswer.utils.logger import setup_logger

from sqlalchemy.orm import Session
from sqlalchemy.exc import IntegrityError

logger = setup_logger()

router = APIRouter(prefix="/paper")


@router.get("/get_paper")
def get_today_papers():
    # return {'type': 'paper'}
    # st = '2024-02-21'
    # start_date = datetime.strptime(st, '%Y-%m-%d').date()
    # end_date = datetime.now().date()
    # categories = ['cs.AI', 'cs.CL', 'cs.LG', 'cs.CV']

    # arxiv_api = ArxivAPI(start_date, end_date)
    # papers = arxiv_api.get(categories)
    # output = {i: {'title': paper.title} for i, paper in enumerate(papers)}
    # return output
    


    # Upload files
    file_path = ['/app/s3/cover_letter.pdf', '/app/s3/resume.pdf']
    api_url = 'http://localhost:8080/manage/admin/connector/file/upload'
    # files = {'files': ('cover_letter.pdf', open(file_path, 'rb'))}
    # files = {'files': tuple([open(p, 'rb') for p in file_path])}
    files = {'files': (open(file_path[0], 'rb'))}
    response = requests.post(api_url, files=files)
    responseJson = response.json()
    if response.status_code == 200:
        print("File uploaded successfully.")
        print(responseJson)
    else:
        print(f"Error uploading file. Status code: {response.status_code}")

    # Create connector
    connector_info = ConnectorBase(
        name = 'FileConnector' + f'{int(time.time() * 1000)}',
        source = 'file',
        input_type = 'load_state',
        connector_specific_config = {'file_locations': responseJson['file_paths']},
        refresh_freq = None,
        disabled = False
    )
    db_session = Session(get_sqlalchemy_engine(), expire_on_commit=False)
    response = create_connector(connector_info, db_session)
    connector_id = response.id
    

    # Create credential
    credential_info = CredentialBase(
        credential_json={},
        admin_public=True
    )
    db_session = Session(get_sqlalchemy_engine(), expire_on_commit=False)
    response = create_credential(credential_info, None, db_session)
    credential_id = response.id


    # Put CC (connector-credential) pair
    now = datetime.now()
    current_time = now.strftime("%Y:%m:%d::%H:%M:%S")
    metadata = ConnectorCredentialPairMetadata(
        name='arxiv_' + current_time
    )
    db_session = Session(get_sqlalchemy_engine(), expire_on_commit=False)
    try:
        response = add_credential_to_connector(
            connector_id=connector_id,
            credential_id=credential_id,
            cc_pair_name=metadata.name,
            user=None,
            db_session=db_session,
        )
    except IntegrityError:
        raise HTTPException(status_code=400, detail="Name must be unique")


    # Connector run
    run_info = RunConnectorRequest(
        connector_id=connector_id,
        credential_ids=None,
        from_beginning=False
    )
    db_session = Session(get_sqlalchemy_engine(), expire_on_commit=False)
    connector_id = run_info.connector_id
    specified_credential_ids = run_info.credential_ids
    try:
        possible_credential_ids = get_connector_credential_ids(
            run_info.connector_id, db_session
        )
    except ValueError:
        raise HTTPException(
            status_code=404,
            detail=f"Connector by id {connector_id} does not exist.",
        )

    if not specified_credential_ids:
        credential_ids = possible_credential_ids
    else:
        if set(specified_credential_ids).issubset(set(possible_credential_ids)):
            credential_ids = specified_credential_ids
        else:
            raise HTTPException(
                status_code=400,
                detail="Not all specified credentials are associated with connector",
            )
        
    if not credential_ids:
        raise HTTPException(
            status_code=400,
            detail="Connector has no valid credentials, cannot create index attempts.",
        )
    
    skipped_credentials = [
        credential_id
        for credential_id in credential_ids
        if get_index_attempts_for_cc_pair(
            cc_pair_identifier=ConnectorCredentialPairIdentifier(
                connector_id=run_info.connector_id,
                credential_id=credential_id,
            ),
            only_current=True,
            disinclude_finished=True,
            db_session=db_session,
        )
    ]

    embedding_model = get_current_db_embedding_model(db_session)

    index_attempt_ids = [
        create_index_attempt(
            connector_id=run_info.connector_id,
            credential_id=credential_id,
            embedding_model_id=embedding_model.id,
            from_beginning=run_info.from_beginning,
            db_session=db_session,
        )
        for credential_id in credential_ids
        if credential_id not in skipped_credentials
    ]
    
    print(index_attempt_ids)
    print()
    print()
    print()
    print()

    if not index_attempt_ids:
        raise HTTPException(
            status_code=400,
            detail="No new indexing attempts created, indexing jobs are queued or running.",
        )
    

    # Indexing status
    indexing_statuses: list[ConnectorIndexingStatus] = []
    cc_pairs = get_connector_credential_pairs(db_session)
    cc_pair_identifiers = [
        ConnectorCredentialPairIdentifier(
            connector_id=cc_pair.connector_id, credential_id=cc_pair.credential_id
        )
        for cc_pair in cc_pairs
    ]

    latest_index_attempts = get_latest_index_attempts(
        connector_credential_pair_identifiers=cc_pair_identifiers,
        secondary_index=False,
        db_session=db_session,
    )
    cc_pair_to_latest_index_attempt = {
        (index_attempt.connector_id, index_attempt.credential_id): index_attempt
        for index_attempt in latest_index_attempts
    }

    document_count_info = get_document_cnts_for_cc_pairs(
        db_session=db_session,
        cc_pair_identifiers=cc_pair_identifiers,
    )
    cc_pair_to_document_cnt = {
        (connector_id, credential_id): cnt
        for connector_id, credential_id, cnt in document_count_info
    }

    for cc_pair in cc_pairs:
        # TODO remove this to enable ingestion API
        if cc_pair.name == "DefaultCCPair":
            continue

        connector = cc_pair.connector
        credential = cc_pair.credential
        latest_index_attempt = cc_pair_to_latest_index_attempt.get(
            (connector.id, credential.id)
        )
        indexing_statuses.append(
            ConnectorIndexingStatus(
                cc_pair_id=cc_pair.id,
                name=cc_pair.name,
                connector=ConnectorSnapshot.from_connector_db_model(connector),
                credential=CredentialSnapshot.from_credential_db_model(credential),
                public_doc=cc_pair.is_public,
                owner=credential.user.email if credential.user else "",
                last_status=cc_pair.last_attempt_status,
                last_success=cc_pair.last_successful_index_time,
                docs_indexed=cc_pair_to_document_cnt.get(
                    (connector.id, credential.id), 0
                ),
                error_msg=latest_index_attempt.error_msg
                if latest_index_attempt
                else None,
                latest_index_attempt=IndexAttemptSnapshot.from_index_attempt_db_model(
                    latest_index_attempt
                )
                if latest_index_attempt
                else None,
                deletion_attempt=get_deletion_status(
                    connector_id=connector.id,
                    credential_id=credential.id,
                    db_session=db_session,
                ),
                is_deletable=check_deletion_attempt_is_allowed(
                    connector_credential_pair=cc_pair
                ),
            )
        )

    print(indexing_statuses)
    print()
    print()
    print()
    print()
    return indexing_statuses
