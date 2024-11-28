import json
import aiohttp
from typing import Any
from fake_useragent import UserAgent
from submodule_integrations.models.integration import Integration
from submodule_integrations.utils.errors import IntegrationAuthError, IntegrationAPIError


class ViventiumIntegration(Integration):
    def __init__(self, user_agent: str = UserAgent().random):
        super().__init__("viventium")
        self.user_agent = user_agent
        self.network_requester = None
        self.url = "https://hcm.viventium.com/api"

    async def initialize(self, network_requester=None):
        self.network_requester = network_requester

    async def _make_request(self, method: str, url: str, **kwargs):
        """
        Helper method to handle network requests using either custom requester or aiohttp
        """
        if self.network_requester:
            response = await self.network_requester.request(
                method, url, process_response=self._handle_response, **kwargs
            )
            return response
        else:
            async with aiohttp.ClientSession() as session:
                async with session.request(method, url, **kwargs) as response:
                    return await self._handle_response(response)

    async def _handle_response(self, response: aiohttp.ClientResponse) -> [str | Any]:
        if response.status in [200, 201, 204]:
            try:
                return await response.json()
            except (json.decoder.JSONDecodeError, aiohttp.ContentTypeError):
                # return await response.read()
                raise IntegrationAPIError(integration_name="viventium",
                                          status_code=response.status,
                                          message=await response.text())

        status_code = response.status
        # do things with fail status codes
        if status_code in [400, 401]:
            # potential auth caused
            reason = response.reason
            r_json = await response.json()
            raise IntegrationAuthError(
                f"ERSP: {status_code} - {reason} \n"
                f"message: {r_json.get('message')} \n"
                f"error_type: {r_json.get('error_type')}"
            )
        else:
            r_json = await response.json()
            raise IntegrationAPIError(
                self.integration_name,
                f"ersp: {status_code} - {response.headers} \n"
                f"message: {r_json.get('message')} \n"
                f"error_type: {r_json.get('error_type')}",
                status_code,
            )

    async def _setup_headers(self, xsrf_token: str):
        _headers = {
            'Host': 'hcm.viventium.com',
            'User-Agent': self.user_agent,
            'Accept': 'application/json, text/plain, */*',
            'Accept-Language': 'en-GB,en;q=0.5',
            'X-XSRF-TOKEN': xsrf_token,
            'Connection': 'keep-alive',
            'Referer': 'https://hcm.viventium.com/apps/vm/',
            'Sec-Fetch-Dest': 'empty',
            'Sec-Fetch-Mode': 'cors',
            'Sec-Fetch-Site': 'same-origin',
        }
        return _headers

    @staticmethod
    def make_cookie_string(cookies: dict) -> str:
        return '; '.join(f"{key}={value}" for key, value in cookies.items())

    async def _get_division_id(self, token: str, cookies: dict | str):
        """
        Retrieves the division ID for the authenticated account using the PayStream API.
        This method should be called before making requests that require a division ID,
        as the token and cookies need to be current for authentication.

        Args:
            token (str): XSRF token for request authentication
            cookies (dict): Session cookies required for authentication

        Returns:
            str: The division ID from the first division in the response list
        """
        endpoint = "paystream/v1/divisions"
        path = f"{self.url}/{endpoint}"
        params = {
            'pageNumber': '1',
            'pageSize': '1000',
        }
        headers = await self._setup_headers(xsrf_token=token)
        if type(cookies) is dict:
            cookies = self.make_cookie_string(cookies)
        headers['Cookie'] = cookies

        response = await self._make_request("GET", path, headers=headers, params=params)
        this_division: dict = response[0]
        return this_division.get("id")

    async def fetch_employee_profiles(self, xsrf_token: str, cookies: dict | str):
        division_id = await self._get_division_id(token=xsrf_token, cookies=cookies)

        headers = await self._setup_headers(xsrf_token=xsrf_token)
        if type(cookies) is dict:
            cookies = self.make_cookie_string(cookies)
        headers['Cookie'] = cookies

        endpoint = f"paystream/v1/divisions/{division_id}/grids/EmployeeProfile"
        path = f"{self.url}/{endpoint}"
        employee_list = []

        page = 1
        while True:
            query_options = {
                "query": "",
                "filterParameters": [
                    {
                        "fieldName": "EmployeeStatus",
                        "filterType": "In",
                        "parsableValue": '["Active"]'
                    }
                ],
                "sortParameters": [
                    {
                        "fieldName": "EmployeeNumber",
                        "direction": "Ascending"
                    }
                ],
                "pageSize": 100,
                "whereParameters": [],
                "pageNumber": page
            }
            # The key is to pass the JSON-encoded string of query_options
            params = {
                "queryOptions": json.dumps(query_options)
            }

            response = await self._make_request("GET", path, headers=headers, params=params)
            employees = response
            if len(employees) > 0:
                employee_list.extend(employees)
            else:
                break

            if len(employees) < 100:
                print(len(employees))
                break

            page += 1

        for employee in employee_list:
            employee.pop('DivisionKey')

        return employee_list
