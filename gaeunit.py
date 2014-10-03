"""
GAEUnit: Google App Engine Unit Test Framework

Usage:

1. Put gaeunit.py into your application directory.  Modify 'app.yaml' by
   adding the following mapping below the 'handlers:' section:

   - url: /test.*
     script: gaeunit.py

2. Write your own test cases by extending unittest.TestCase.

3. Launch the development web server.  To run all tests, point your browser to:

   http://localhost:8080/test     (Modify the port if necessary.)

   For plain text output add '?format=plain' to the above URL.
   See README.TXT for information on how to run specific tests.

4. The results are displayed as the tests are run.

Visit http://code.google.com/p/gaeunit for more information and updates.

------------------------------------------------------------------------------
Copyright (c) 2008-2009, George Lei and Steven R. Farley.  All rights reserved.

Distributed under the following BSD license:

Redistribution and use in source and binary forms, with or without
modification, are permitted provided that the following conditions are met:

* Redistributions of source code must retain the above copyright notice,
  this list of conditions and the following disclaimer.

* Redistributions in binary form must reproduce the above copyright notice,
  this list of conditions and the following disclaimer in the documentation
  and/or other materials provided with the distribution.

THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDERS AND CONTRIBUTORS "AS IS"
AND ANY EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT LIMITED TO, THE
IMPLIED WARRANTIES OF MERCHANTABILITY AND FITNESS FOR A PARTICULAR PURPOSE ARE
DISCLAIMED. IN NO EVENT SHALL THE COPYRIGHT OWNER OR CONTRIBUTORS BE LIABLE
FOR ANY DIRECT, INDIRECT, INCIDENTAL, SPECIAL, EXEMPLARY, OR CONSEQUENTIAL
DAMAGES (INCLUDING, BUT NOT LIMITED TO, PROCUREMENT OF SUBSTITUTE GOODS OR
SERVICES; LOSS OF USE, DATA, OR PROFITS; OR BUSINESS INTERRUPTION) HOWEVER
CAUSED AND ON ANY THEORY OF LIABILITY, WHETHER IN CONTRACT, STRICT LIABILITY,
OR TORT (INCLUDING NEGLIGENCE OR OTHERWISE) ARISING IN ANY WAY OUT OF THE USE
OF THIS SOFTWARE, EVEN IF ADVISED OF THE POSSIBILITY OF SUCH DAMAGE.
------------------------------------------------------------------------------
Modified by Love Sharma (contact@lovesharma.com).
"""


import cgi
import json
import logging
import os
import sys
import time
import unittest
import webapp2

# pylint: disable=F0401
from google.appengine.api import apiproxy_stub_map
from google.appengine.api import datastore_file_stub
from google.appengine.ext.webapp import template

_LOCAL_TEST_DIR = 'test'  # location of files
_WEB_TEST_DIR = '/test'   # how you want to refer to tests on your web server


class MainTestPageHandler(webapp2.RequestHandler):

    """Main handler, shows statuses of all test cases."""

    def get(self):
        """GET request method."""
        package_name = self.request.get("package")
        test_name = self.request.get("name")
        self.response.headers['Content-Type'] = 'text/html'
        suite, error = _create_suite(package_name, test_name, _LOCAL_TEST_DIR)
        if not error:
            content = template.render(
                os.path.join(os.path.dirname(__file__), 'gaetests.html'),
                {'suites': _test_suite_to_json(suite), 'dir': _WEB_TEST_DIR}
            )
            self.response.out.write(content)
        else:
            self.error(404)
            self.response.out.write(error)


class JsonTestResult(unittest.TestResult):

    """Individual test case handler, result in json output."""

    def __init__(self):
        unittest.TestResult.__init__(self)
        self.test_number = 0

    def render_to(self, stream):
        """Returns output in json format."""
        make_list = lambda lst: [{'desc': test.shortDescription() or str(test),
                                  'detail': cgi.escape(err)}
                                 for test, err in lst]
        result = {
            'runs': self.testsRun,
            'total': self.test_number,
            'errors': make_list(self.errors),
            'failures': make_list(self.failures),
            'time_taken': self.time_taken
        }
        stream.write(json.dumps(result).replace('},', '},\n'))


class JsonTestRunner(object):  # pylint: disable=R0903

    """Test Runner to execute Individual test."""
    result = None

    def run(self, test):
        """Override run method, one for each test."""
        self.result = JsonTestResult()
        self.result.test_number = test.countTestCases()
        start_time = time.clock()
        test(self.result)
        stop_time = time.clock()
        self.result.time_taken = stop_time - start_time
        return self.result


class JsonTestRunHandler(webapp2.RequestHandler):

    """JsonTestRun Request handler, returns test status in json format."""

    def get(self):
        """GET Request, Returns tests status."""
        self.response.headers["Content-Type"] = "text/javascript"
        test_name = self.request.get("name")
        _load_default_test_modules(_LOCAL_TEST_DIR)
        suite = unittest.defaultTestLoader.loadTestsFromName(test_name)
        runner = JsonTestRunner()
        _run_test_suite(runner, suite)
        runner.result.render_to(self.response.out)


def _create_suite(package_name, test_name, test_dir):
    """
    Prepares suite by looking at package, Individual test from test directory.
    """
    loader = unittest.defaultTestLoader
    suite = unittest.TestSuite()

    error = None

    try:
        if not package_name and not test_name:
            modules = _load_default_test_modules(test_dir)
            for module in modules:
                suite.addTest(loader.loadTestsFromModule(module))
        elif test_name:
            _load_default_test_modules(test_dir)
            suite.addTest(loader.loadTestsFromName(test_name))
        elif package_name:
            package = reload(__import__(package_name))
            module_names = package.__all__
            for module_name in module_names:
                suite.addTest(loader.loadTestsFromName(
                    '%s.%s' % (package_name, module_name)))

        if suite.countTestCases() == 0:
            raise Exception(
                "'%s' is not found or does not contain any tests." %
                (test_name or package_name or
                 'local directory: \"%s\"' % _LOCAL_TEST_DIR))
    except Exception as excp:  # pylint: disable=W0703
        print excp
        error = str(excp)
        _log_error(error)

    return (suite, error)


def _load_default_test_modules(test_dir):
    """Load all available tests from default test directory."""
    if not test_dir in sys.path:
        sys.path.append(test_dir)
    module_names = [mf[0:-3]
                    for mf in os.listdir(test_dir) if mf.endswith(".py")]
    return [reload(__import__(name)) for name in module_names]


def _get_tests_from_suite(suite, tests):
    """Flattens tests from Individual suite."""
    for test in suite:
        if isinstance(test, unittest.TestSuite):
            _get_tests_from_suite(test, tests)
        else:
            tests.append(test)


def _test_suite_to_json(suite):
    """Returns test suites in json format."""
    tests = []
    _get_tests_from_suite(suite, tests)
    test_tuples = [(type(test).__module__, type(test).__name__,
                    str(test).split()[0]) for test in tests]
    test_dict = {}
    for test_tuple in test_tuples:
        module_name, class_name, method_name = test_tuple
        if module_name not in test_dict:
            mod_dict = {}
            method_list = []
            method_list.append(method_name)
            mod_dict[class_name] = method_list
            test_dict[module_name] = mod_dict
        else:
            mod_dict = test_dict[module_name]
            if class_name not in mod_dict:
                method_list = []
                method_list.append(method_name)
                mod_dict[class_name] = method_list
            else:
                method_list = mod_dict[class_name]
                method_list.append(method_name)
    return json.dumps(test_dict)


def _run_test_suite(runner, suite):
    """Run the test suite.

    Preserve the current development apiproxy, create a new apiproxy and
    replace the datastore with a temporary one that will be used for this
    test suite, run the test suite, and restore the development apiproxy.
    This isolates the test datastore from the development datastore.

    """
    original_apiproxy = apiproxy_stub_map.apiproxy
    try:
        apiproxy_stub_map.apiproxy = apiproxy_stub_map.APIProxyStubMap()
        temp_stub = datastore_file_stub.DatastoreFileStub(
            'GAEUnitDataStore', None, None, trusted=True)
        apiproxy_stub_map.apiproxy.RegisterStub('datastore', temp_stub)
        # Allow the other services to be used as-is for tests.
        for name in ['user', 'urlfetch', 'mail', 'memcache', 'images',
                     'blobstore', 'logservice']:
            apiproxy_stub_map.apiproxy.RegisterStub(
                name, original_apiproxy.GetStub(name))
        runner.run(suite)
    finally:
        apiproxy_stub_map.apiproxy = original_apiproxy


def _log_error(msg):
    """Print warning logs and returns same msg."""
    logging.warn(msg)
    return msg


APPLICATION = webapp2.WSGIApplication([
    webapp2.Route('%s' % _WEB_TEST_DIR, MainTestPageHandler),
    webapp2.Route('%s/run' % _WEB_TEST_DIR, JsonTestRunHandler)
], debug=True)
