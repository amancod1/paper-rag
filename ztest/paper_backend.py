import requests
from datetime import datetime

from fastapi import APIRouter
from paper_api import ArxivAPI


router = APIRouter(prefix="/paper")


@router.get("/get_paper")
def get_today_papers():
    # st = '2024-02-22'
    # start_date = datetime.strptime(st, '%Y-%m-%d').date()
    # end_date = datetime.now().date()
    # categories = ['cs.AI', 'cs.CL', 'cs.LG', 'cs.CV']

    # arxiv_api = ArxivAPI(start_date, end_date)
    # papers = arxiv_api.get(categories)
    # output = {i: {'title': paper.title} for i, paper in enumerate(papers)}
    # return output
    file_path = '/Users/ljm/Desktop/private/cover_letter.pdf'

    # API endpoint URL
    api_url = '/manage/admin/connector/file/upload'

    # Prepare the files to be uploaded
    files = {'files': ('cover_letter.pdf', open(file_path, 'rb'))}

    # Make the POST request to the API endpoint
    response = requests.post(api_url, files=files)

    # Check the response
    if response.status_code == 200:
        print("File uploaded successfully.")
        print(response.json())
    else:
        print(f"Error uploading file. Status code: {response.status_code}")
        print(response.text)

