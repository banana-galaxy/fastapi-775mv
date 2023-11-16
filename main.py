import time
import uuid
#from pymongo import MongoClient
from motor import motor_asyncio
from fastapi import FastAPI, Request
from pprint import pprint
from json import loads
from authorizenet import apicontractsv1
from authorizenet.apicontrollers import createTransactionController
import re

app = FastAPI()

class SiteDB:
    def __init__(self):
        #self.db = MongoClient('localhost', 27017)['775mv_dev']
        self.db = motor_asyncio.AsyncIOMotorClient('localhost', 27017)['775mv_dev']

    async def get_collection_as_list(self, collection: str):
        documents = []
        db_collection = self.db[collection]
        for i in await db_collection.find():
            i['_id'] = str(i['_id'])
            documents.append(i)
        return documents

    async def get_document(self, collection: str, document: dict):
        documents = self.db[collection]
        doc = await documents.find_one(document)
        doc['_id'] = str(doc['_id'])
        return doc

    async def post_document(self, collection: str, document: dict):
        documents = self.db[collection]
        return await documents.insert_one(document)

db = SiteDB()

@app.get("/")
async def root():
    return {"message": "Hello World"}


@app.get("/hello/{name}")
async def say_hello(name: str):
    return {"message": f"Hello {name}"}


@app.get("/get-products")
async def get_products():
    #print(db.get_collection_as_list('product-information'))
    required_fields = ['_id', 'sku', 'name', 'price', 'description']
    checked_docs = []
    for i in await db.get_collection_as_list('product-information'):
        checked = True
        for field in required_fields:
            if field not in i.keys():
                checked = False
        if checked:
            checked_docs.append(i)
    for i, x in enumerate(checked_docs):
        x['id'] = i
    pprint(checked_docs)
    time.sleep(3)
    return checked_docs#db.get_collection_as_list('product-information')
    #return {'products': [{'name': 'filter', 'price': 20}, {'name': 'filter2', 'price': 10}]}


@app.get("/get-product/{sku}")
async def product(sku: str):
    print(sku)
    doc = await db.get_document('product-information', {'sku': sku})
    with open('static/pen_holder/desc.md') as f:
        doc['desc'] = f.read()
    with open('static/pen_holder/specs.md') as f:
        doc['specs'] = f.read()

    return doc


@app.get("/session-id")
async def new_session_id():
    doc = await db.post_document('accounts', {
        "email": "",
        "password": "",
        "cart": [],
        "orders": []
    })

    uid = str(uuid.uuid4())

    await db.post_document('sessions', {
        "id": uid,
        "account": doc.inserted_id
    })

    return {"sessionId": uid}


@app.post("/add-to-cart", status_code=200)
async def add_to_cart(request: Request):
    res = await request.body()
    res = loads(res.decode())
    session = await db.get_document('sessions', {'id': res['sessionId']})
    account_id = session['account']
    account = await db.get_document('accounts', {'_id': account_id})

    cart_index = -1
    for i, x in enumerate(account['cart']):
        if x['sku'] == res['sku']:
            cart_index = i

    if cart_index != -1:
        account['cart'][cart_index]['amount'] += res['amount']
    else:
        account['cart'].append({'sku': res['sku'], 'amount': res['amount'], 'checkout': True})

    await db.db['accounts'].update_one({'_id': account_id}, {'$set': {'cart': account['cart']}})


    #print(loads(res.decode()))
    return res

@app.post("/cart", status_code=200)
async def get_cart(request: Request):
    res = await request.body()
    print(res)
    res = loads(res.decode())
    print(res)
    if "sessionId" not in res.keys():
        return []
    session = await db.get_document('sessions', {'id': res['sessionId']})
    account_id = session['account']
    account = await db.get_document('accounts', {'_id': account_id})

    for item in account['cart']:
        db_item = await db.get_document('product-information', {'sku': item['sku']})
        item['price'] = db_item['price']
        item['name'] = db_item['name']
        item['description'] = db_item['description']

    return account['cart']

@app.post("/update-cart")
async def update_cart(request: Request):
    result = "ok"
    res = await request.body()
    print(res)
    res = loads(res.decode())
    print(res)
    session = await db.get_document('sessions', {'id': res['sessionId']})
    account_id = session['account']
    account = await db.get_document('accounts', {'_id': account_id})

    if res['type'] == "checkout":
        for item in account['cart']:
            if item['sku'] == res['sku']:
                item['checkout'] = res['value']
                break
        await db.db['accounts'].update_one({'_id': account_id}, {'$set': {'cart': account['cart']}})
    elif res['type'] == "amount":
        amount = 1
        if res['value'].isdigit():
            print("isdigit")
            amount = int(res['value'])
            if amount < 1:
                result = "denied"
            else:
                for item in account['cart']:
                    if item['sku'] == res['sku']:
                        item['amount'] = amount
                        break
                await db.db['accounts'].update_one({'_id': account_id}, {'$set': {'cart': account['cart']}})
        elif res['value'] == "":
            for item in account['cart']:
                if item['sku'] == res['sku']:
                    item['amount'] = 1
                    break
        else:
            result = "denied"
    elif res['type'] == "delete":
        i = 0
        deleted = False
        while i < len(account['cart']) and not deleted:
            if account['cart'][i]['sku'] == res['sku']:
                account['cart'].pop(i)
                deleted = True
            i += 1
        await db.db['accounts'].update_one({'_id': account_id}, {'$set': {'cart': account['cart']}})
    else:
        pass

    return {"result": result}

@app.post("/authorize")
async def authorize(request: Request):
    """
    Authorize a credit card (without actually charging it)
    """

    res = await request.body()
    # print(res)
    res = loads(res.decode())
    # print(res)
    session = await db.get_document('sessions', {'id': res['sessionId']})
    account_id = session['account']
    account = await db.get_document('accounts', {'_id': account_id})

    print(res)

    # Check for shipping information
    for item in res['items']:
        if item != ['expanded']:
            print(res["items"]["billing"]["same_as_shipping"])
            if item == "billing" and res["items"]["billing"]["same_as_shipping"]:
                print('GOT HERE')
                continue
            for i in res['items'][item].keys():
                if res['items'][item][i] == "" and i != "address2":
                    return {"result": f"missing {item} {i}"}

    return {"result" : f"success"}

    '''# Create a merchantAuthenticationType object with authentication details
    # retrieved from the constants file
    merchantAuth = apicontractsv1.merchantAuthenticationType()
    merchantAuth.name = "34UTh2qF6d"
    merchantAuth.transactionKey = "49F877p4KvPBUgwR"

    # Create the payment data for a credit card
    creditCard = apicontractsv1.creditCardType()
    creditCard.cardNumber = "4111111111111111"
    creditCard.expirationDate = "2035-12"
    creditCard.cardCode = "123"

    # Add the payment data to a paymentType object
    payment = apicontractsv1.paymentType()
    payment.creditCard = creditCard

    # Create order information
    order = apicontractsv1.orderType()
    order.invoiceNumber = str(order_id)

    # Set the customer's Bill To address
    customerAddress = apicontractsv1.customerAddressType()
    customerAddress.firstName = webdata['contact']['name'].split(' ')[0]
    customerAddress.lastName = ' '.join(webdata['contact']['name'].split(' ')[1:])
    if webdata['billing']['use shipping address']:
        customerAddress.address = webdata['shipping']['address'] + f'\n{webdata["shipping"]["address2"]}' if webdata["shipping"]["address2"] != '' else ''
        customerAddress.city = webdata['shipping']['city']
        customerAddress.state = webdata['shipping']['state']
        customerAddress.zip = webdata['shipping']['zip']
        customerAddress.country = webdata['shipping']['country']
    else:
        customerAddress.address = webdata['billing']['address'] + f'\n{webdata["billing"]["address2"]}' if webdata["billing"]["address2"] != '' else ''
        customerAddress.city = webdata['billing']['city']
        customerAddress.state = webdata['billing']['state']
        customerAddress.zip = webdata['billing']['zip']
        customerAddress.country = webdata['billing']['country']

    # Set the customer's identifying information
    # customerData = apicontractsv1.customerDataType()
    # customerData.type = "individual"
    # customerData.id = "99999456654"
    # customerData.email = "EllenJohnson@example.com"

    # Add values for transaction settings
    duplicateWindowSetting = apicontractsv1.settingType()
    duplicateWindowSetting.settingName = "duplicateWindow"
    duplicateWindowSetting.settingValue = "1" # 600
    settings = apicontractsv1.ArrayOfSetting()
    settings.setting.append(duplicateWindowSetting)

    # setup individual line items & build the array of line items
    line_items = apicontractsv1.ArrayOfLineItem()
    for item in webdata['cart']:
        line_item = apicontractsv1.lineItemType()
        line_item.itemId = item['sku']
        line_item.name = item['sku'].split('-')[0]
        line_item.description = ' '.join(item['sku'].split('-')[1:])
        line_item.quantity = item['quantity']
        line_item.unitPrice = item['unit_price']
        line_items.lineItem.append(line_item)

    line_item = apicontractsv1.lineItemType()
    line_item.itemId = 'shipping'
    line_item.name = 'Shipping price'
    line_item.description = 'The shipping cost'
    line_item.quantity = '1'
    line_item.unitPrice = shipping_price
    line_items.lineItem.append(line_item)

    # Create a transactionRequestType object and add the previous objects to it.
    transactionrequest = apicontractsv1.transactionRequestType()
    transactionrequest.transactionType = "authOnlyTransaction"
    transactionrequest.amount = total_price
    transactionrequest.payment = payment
    transactionrequest.order = order
    transactionrequest.billTo = customerAddress
    transactionrequest.transactionSettings = settings
    transactionrequest.lineItems = line_items

    # Assemble the complete transaction request
    createtransactionrequest = apicontractsv1.createTransactionRequest()
    createtransactionrequest.merchantAuthentication = merchantAuth
    createtransactionrequest.refId = "MerchantID-0001"
    createtransactionrequest.transactionRequest = transactionrequest
    # Create the controller
    createtransactioncontroller = createTransactionController(
        createtransactionrequest)
    createtransactioncontroller.execute()

    response = createtransactioncontroller.getresponse()

    if response is not None:
        # Check to see if the API request was successfully received and acted upon
        if response.messages.resultCode == "Ok":
            # Since the API request was successful, look for a transaction response
            # and parse it to display the results of authorizing the card
            if hasattr(response.transactionResponse, 'messages') is True:
                print(
                    'Successfully created transaction with Transaction ID: %s'
                    % response.transactionResponse.transId)
                print('Transaction Response Code: %s' %
                      response.transactionResponse.responseCode)
                print('Message Code: %s' %
                      response.transactionResponse.messages.message[0].code)
                print('Description: %s' % response.transactionResponse.
                      messages.message[0].description)
                return response.transactionResponse.transId
            else:
                print('Failed Transaction.')
                if hasattr(response.transactionResponse, 'errors') is True:
                    print('Error Code:  %s' % str(response.transactionResponse.
                                                  errors.error[0].errorCode))
                    print(
                        'Error message: %s' %
                        response.transactionResponse.errors.error[0].errorText)
        # Or, print errors if the API request wasn't successful
        else:
            print('Failed Transaction.')
            if hasattr(response, 'transactionResponse') is True and hasattr(
                    response.transactionResponse, 'errors') is True:
                print('Error Code: %s' % str(
                    response.transactionResponse.errors.error[0].errorCode))
                print('Error message: %s' %
                      response.transactionResponse.errors.error[0].errorText)
            else:
                print('Error Code: %s' %
                      response.messages.message[0]['code'].text)
                print('Error message: %s' %
                      response.messages.message[0]['text'].text)
    else:
        print('Null Response.')

    return 'fail'''