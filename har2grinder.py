#!/usr/bin/python
import getopt
import sys
import json
try:
    from urllib.parse import urlparse
except ImportError:
     from urlparse import urlparse

# Load settings from settings.py
try:
    import settings
except ImportError as e:
    sys.stderr.write("No settings.py file found, will use default values.\n")


def usage():
    print("Usage: " + __file__ + """ har_file
Please provide a HAR file generated by Chrome Dev Tools.
""")
    sys.exit(2)

def prepare_entry_headers(entry, header_to_libidx, header_lib):
    headers = entry.get('request').get('headers')
    test_number = entry.get('grinder').get('test_number')

    entry_headers = ''
    for header in headers:
        # we build up header_lib as we go: this is an array of header
        # name,value tuples. header_to_libidx is a dictionary mapping
        # from each header tuple to its index in the header_lib
        name_val = header.get('name'), header.get('value')
        if name_val[0] not in ["accept-encoding", "accept-language", "content-type", "accept", "user-agent"]:
            continue
        if name_val not in header_to_libidx:
            header_lib.append(name_val)
            libidx = len(header_lib) - 1
            header_to_libidx[name_val] = libidx
        else:
            libidx = header_to_libidx[name_val]

        # instead of NVPair() statements, we use the existing header_lib entry
        entry_headers += "  header_lib[%d],\n" % (libidx,)

    entry_headers = "headers%i = [%s]\n" % (test_number, entry_headers)

    return entry_headers


def prepare_entry_request_call(entry):
    test_number = entry.get('grinder').get('test_number')
    parsed_url = entry.get('grinder').get('parsed_url')
    request = entry.get('request')
    method = request.get('method')
    url = request.get('url')

    grinder_url = "%s://%s" % (parsed_url.scheme, parsed_url.netloc)
    grinder_path = url[len(grinder_url)+1:]

    post_data = request.get('postData')
    if post_data:
        param_code = ''
        if post_data.get('params'):
            for parameter in post_data.get('params'):
                param_code += "            NVPair('%s', '%s'),\n" % (parameter.get('name'), parameter.get('value'))

        param_code = param_code[12:-1]
        request_call = "        request%i.%s('%s', (%s))\n" % (test_number, method, grinder_path, param_code)
    else:
        request_call = "        request%i.%s('%s')\n" % (test_number, method, grinder_path)

    return request_call


def main():
    try:
        (opts, args) = getopt.getopt(sys.argv[1:], '')
    except getopt.GetoptError:
        # Print help information and exit:
        usage()
    
    # Check expected number of arguments (at least one filename)
    if len(args) != 1:
        usage()
        
    # Set default option values if not defined in settings.py
    EXCLUDED_DOMAINS = getattr(settings, 'EXCLUDED_DOMAINS', ())
    SLEEP_BETWEEN_PAGES = getattr(settings, 'SLEEP_BETWEEN_PAGES', 3000)
    FIRST_PAGE_NUMBER = getattr(settings, 'FIRST_PAGE_NUMBER', 0)	

    # Load HAR input file
    input_file_name = args[0]
    try:
        input_file = open(input_file_name, 'r', encoding='utf-8')
        input_json = input_file.read()
    except IOError:
        print('Error: could not open ' + input_file_name + ' for reading. Exiting.')
        sys.exit(2)

    # Parse HAR input JSON
    try:
        har_data = json.loads(input_json)
    except Exception:
        print('Error: could parse HAR file ' + input_file_name + '. Exiting.')
        sys.exit(2)

    page_by_id = {}
    requests_section = ''
    headers_section = ''
    page_section = ''
    call_section = ''
    instruments_section = ''

    ordered_pages = sorted(har_data.get('log').get('pages'), key=lambda p: int(p['id'].replace("page_", "")))
	
    # Process data from loaded HAR file
    page_number = FIRST_PAGE_NUMBER
    for page in ordered_pages:
        page_number += 1
        page['grinder'] = {}
        page['grinder']['entries'] = []

        page['grinder']['test_number'] = page_number * 1000
        page['grinder']['highest_test_number'] = page['grinder']['test_number']
        page['grinder']['function_code'] = ''
        page_by_id[page.get('id')] = page

    # prepare_entry_headers will build up this header library and lookup table
    header_to_libidx = {}
    header_lib = []

    entries = har_data.get('log').get('entries')
    for entry in entries:
        cache = entry.get('_fromCache')
        if cache in ["memory", "disk"]:
            continue
        request = entry.get('request')
        response = entry.get('response')
        url = request.get('url')
        parsed_url = urlparse(url)
        if parsed_url.netloc in EXCLUDED_DOMAINS:
            continue

        page_id = entry.get('pageref')
        page = page_by_id[page_id]
        page['grinder']['highest_test_number'] += 1
        test_number = page['grinder']['highest_test_number']

        entry['grinder'] = {}
        entry['grinder']['test_number'] = test_number
        entry['grinder']['parsed_url'] = parsed_url

        method = request.get('method')
        path = parsed_url.path
        grinder_url = "%s://%s" % (parsed_url.scheme, parsed_url.netloc)

        requests_section += "request%i = createRequest(Test(%i, '%s %s'), '%s', headers%i)\n" % \
                            (test_number, test_number, method, path, grinder_url, test_number)

        # response_size = response.get('bodySize')
        # requests_section += "request%i = createRequest(Test(%i, '%i %s %s'), '%s', headers%i)\n" % \
        #                     (test_number, test_number, response_size, method, path, grinder_url, test_number)


        headers_section += prepare_entry_headers(
            entry, header_to_libidx, header_lib)

        page['grinder']['function_code'] += prepare_entry_request_call(entry)


    # each of our requests / entries uses a different set of headers that it
    # references from the header_lib by index. That header_lib is constructed
    # here.
    header_library_section = 'header_lib = [\n'
    for nvidx, name_val in enumerate(header_lib):
        header_library_section += "NVPair ('%s', '%s'), # %d\n" % \
                                  (name_val[0], name_val[1], nvidx)

    header_library_section += ']\n'

    page_number = FIRST_PAGE_NUMBER
    for page in ordered_pages:
        page_number += 1

        test_number = page.get('grinder').get('test_number')
        function_code = page.get('grinder').get('function_code')[8:]
        page_section += "    # %s\n" % page.get('title')
        page_section += "    # %s\n" % page.get('id')
        page_section += "    def page%i(self):\n        %s\n" \
                        % (page_number, function_code)

        if page_number == (FIRST_PAGE_NUMBER + 1):
            call_section += '        self.page%i()\n' % (page_number, )
        else:
            call_section += '        grinder.sleep(%i)\n        self.page%i()\n' % (SLEEP_BETWEEN_PAGES, page_number)

        instruments_section += "Test(%i, '%s').record(TestRunner.page%i)\n" \
                               % (test_number, page.get('id'), page_number)

    output = """# The Grinder 3.11
# HTTP script recorded by har2grinder

from net.grinder.script import Test
from net.grinder.script.Grinder import grinder
from net.grinder.plugin.http import HTTPPluginControl, HTTPRequest
from HTTPClient import NVPair
connectionDefaults = HTTPPluginControl.getConnectionDefaults()
httpUtilities = HTTPPluginControl.getHTTPUtilities()

# To use a proxy server, uncomment the next line and set the host and port.
# connectionDefaults.setProxyServer("localhost", 8001)

def createRequest(test, url, headers=None):
    request = HTTPRequest(url=url)
    if headers: request.headers=headers
    test.record(request, HTTPRequest.getHttpMethodFilter())
    return request

# These definitions at the top level of the file are evaluated once,
# when the worker process is started.

connectionDefaults.defaultHeaders = []

# without this, the grinder seems to remove the cookies we might have in
# our headers.
# http://grinder.sourceforge.net/g3/http-plugin.html
connectionDefaults.useCookies = 0

# HEADER LIBRARY SECTION
%s

#HEADERS SECTION
%s

# REQUESTS SECTION
%s

class TestRunner:
    \"\"\"A TestRunner instance is created for each worker thread.\"\"\"
%s
    def __call__(self):
        \"\"\"Called for every run performed by the worker thread.\"\"\"
%s

# Instrument page methods.
%s
""" % (header_library_section, headers_section, requests_section, page_section, call_section, instruments_section)

    print(output)


if __name__ == "__main__":
    main()
