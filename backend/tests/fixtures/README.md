# Password-protected roster fixture

`password_protected_roster.zlib.b64` is a zlib-compressed, base64-encoded
Office Agile encrypted `.xlsx`, containing one fictional Test Employee shift
and six OFF days. It contains no client data.

Generated once with openpyxl and msoffcrypto-tool 5.4.2:
`OOXMLFile(plain_workbook).encrypt("fixture-password-only", encrypted_output)`.
Decrypting the result with that test-only password was verified to return
the original workbook bytes. The encryption tool is not required by the app
or the tests; tests decode the fixture with Python's standard library.
