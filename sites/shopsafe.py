import random
import threading
import time
import traceback
from os.path import exists

from bs4 import BeautifulSoup
import requests, re
import urllib3
from selenium import webdriver
from selenium.webdriver.chrome.options import Options

from utils import return_data, format_proxy, load_session, save_session, delete_session, get_country_code
from webhook import good_web, failed_web, cart_web


class Shopsafe:
    def __init__(self, task_id, status_signal, product_signal, product, info, size, profile, proxy, monitor_delay, error_delay, qty):
        self.task_id, self.status_signal, self.product_signal, self.product, self.info, self.size, self.profile, self.monitor_delay, self.error_delay, self.qty = task_id, status_signal, product_signal, product, info, size, profile,monitor_delay, error_delay, qty
        self.session = requests.Session()
        self.settings = return_data("./data/settings.json")
        self.proxy_list = proxy
        self.session.verify = False
        urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

        if self.proxy_list != False:
            self.update_random_proxy()
        self.product_kws = self.product.split(' [')[0].strip()
        self.title = ''
        self.size_label = ''
        self.image = ''
        self.main_site = self.info
        self.size_kw = self.size
        self.status_signal.emit({"msg": "Starting", "status": "normal"})
        self.variant = ''
        self.status_signal.emit({"msg": "Opening Browser", "status": "normal"})
        options = Options()
        options.headless = False
        options.add_argument("window-size=800,600")
        options.add_argument('enable-automation')
        options.add_argument('--no-sandbox')
        options.add_argument('--disable-dev-shm-usage')
        options.add_argument('--disable-browser-side-navigation')
        options.add_argument('--disable-gpu')
        options.add_argument('log-level=3')
        options.add_experimental_option("excludeSwitches", ["enable-automation"])
        options.add_experimental_option('useAutomationExtension', False)
        options.add_argument('disable-infobars')
        self.driver = webdriver.Chrome(options=options)
        self.driver.get(str(self.main_site))
        self.auth_token = ''
        self.check_site()
        self.monitor()
        self.cart()

        self.submit_shipping()
        self.submit_rates()
        self.price, self.gateway = self.calc_taxes()
        self.submit_payment()

    def get_checkout_token(self, html):
        ind = html.index("authenticity_token")
        sub = str(html[ind:])
        spli = sub.split("\"")[2]
        return spli

    def compare_kw(self, item_name, kws):
        item_comp = item_name.lower()
        for keyword in kws.split(' '):
            kw = str(keyword).lower()
            if '-' in keyword:
                if kw[1::] in item_comp:
                    return False
            else:
                if kw not in item_comp:
                    return False
        return True

    def get_gateway(self, html):
        ind = html.index("data-select-gateway=")
        sub = str(html[ind:])
        spli = sub.split("\"")[1]
        return spli

    def get_price(self, html):
        try:
            ind = html.index('"totalPrice":{"amount":')
            sub = str(html[ind:])
            spli = sub.split(":")[2].split(',')[0]
            if len(spli.split('.')[1]) > 1:
                return spli.replace('.', '')
            else:
                return spli.replace('.','') + ('0' if '.0' not in spli else '')
        except:
            ind = html.index('data-checkout-payment-due-target="')
            sub = str(html[ind:])
            spli = sub.split("\"")[1]
            return spli

    def format_phone(self, phone):
        return '+1' + re.sub('[^A-Za-z0-9]+', '', phone).strip()

    def format_phone2(self, phone):
        phony = re.sub('[^A-Za-z0-9]+', '', phone).strip()
        return '(' + phony[:3] + ') ' + phony[3:6] + "-" + phony[-4:]

    def get_session(self):
        self.status_signal.emit({"msg": "Checking for session", "status": "normal"})
        session = load_session(self.profile['shipping_email'], self.main_site)
        if session == False:
            self.browser_login()
        else:
            for cookies in session[0]:
                self.session.cookies.set(cookies, session[0][cookies])
            self.status_signal.emit({"msg": "Validating session", "status": "normal"})
            account_get = self.session.get(self.main_site + 'account')
            if 'login' in account_get.url:
                delete_session(self.profile['shipping_email'], self.main_site)
                self.browser_login()
            else:
                self.status_signal.emit({"msg": "Valid session found!", "status": "normal"})

    # This code handles logging in for Pimoroni
    def browser_login(self):
        self.status_signal.emit({"msg": "Awaiting Login", "status": "normal"})
        options = Options()
        options.headless = False
        options.add_argument("window-size=800,600")
        options.add_argument('enable-automation')
        options.add_argument('--no-sandbox')
        options.add_argument('--disable-dev-shm-usage')
        options.add_argument('--disable-browser-side-navigation')
        options.add_argument('--disable-gpu')
        options.add_argument('log-level=3')
        options.add_experimental_option("excludeSwitches", ["enable-automation"])
        options.add_experimental_option('useAutomationExtension', False)
        options.add_argument('disable-infobars')
        driver = webdriver.Chrome(options=options)
        driver.get(str(self.main_site + 'account/login'))
        while True:
            while 'login' in driver.current_url or '/challenge' in driver.current_url:
                time.sleep(0.1)
            self.status_signal.emit({"msg": "Checking login session", "status": "normal"})

            for cookie in driver.get_cookies():
                self.session.cookies.set(cookie['name'], cookie['value'], domain=cookie['domain'], path=cookie['path'])

            account_check = self.session.get(f'{self.main_site}account')
            if 'login' not in account_check.url:
                self.status_signal.emit({"msg": "Session valid!", "status": "normal"})
                driver.close()
                save_session(self.profile['shipping_email'], self.main_site, self.session)
                return
            else:
                self.status_signal.emit({"msg": "Session invalid, please retry", "status": "normal"})
                driver.delete_all_cookies()
                driver.refresh()
    def check_site(self):
        password = False
        while True:
            try:
                self.status_signal.emit({"msg": "Checking site", "status": "checking"})
                site_check = self.session.get(self.main_site)
                if site_check.url.endswith('/password'):
                    password = True
                    self.status_signal.emit({"msg": "Password page up", "status": "monitoring"})
                    time.sleep(float(self.monitor_delay))
                else:
                    if 'shopify.com' in site_check.text:
                        if password:
                            self.driver.get(self.main_site)
                        return True
                    else:
                        self.status_signal.emit({"msg": "Not a valid Shopify site", "status": "error"})
                        return False
            except:
                print(traceback.format_exc())
                self.status_signal.emit({"msg": "Error checking site", "status": "error"})
                time.sleep(float(self.monitor_delay))
    def browser_to_session(self):
        for cookie in self.driver.get_cookies():
            self.session.cookies.set(cookie['name'], cookie['value'])
    def session_to_browser(self):
        for cookie in self.session.cookies:
            self.driver.add_cookie({'name': cookie.name, 'value': cookie.value, 'path': cookie.path, 'domain': cookie.domain})
    def cart(self):
        cart_form = {'id': self.variant, 'qty': self.qty}
        self.status_signal.emit({"msg": "Fetching item properties", "status": "normal"})
        prop_get = self.session.get(f"{self.main_site}products/{self.handle}")
        soup = BeautifulSoup(prop_get.content, 'html.parser')
        for prop in soup.find('form', {'action': '/cart/add'}).find_all('input'):
            if prop.has_attr('name') and str(prop.get('name')) not in cart_form and str(prop.get('name')) != 'button':
                cart_form[str(prop.get('name'))] = str(prop.get('value'))
        self.status_signal.emit({"msg": "Adding to cart", "status": "normal"})
        url_to_post = f'{self.main_site}cart/add.js'
        self.session.post(url_to_post, data=cart_form, headers=self.request_headers(self.main_site))
        # We send the cart data to the cart url
        self.start = time.time()
        self.status_signal.emit({"msg": "Visiting cart", "status": "normal"})
        cart_get = self.session.get(f"{self.main_site}cart")
        cart_proceed = {'checkout': 'Checkout'}
        soup = BeautifulSoup(cart_get.content, 'html.parser')
        try:
            for prop in soup.find('form', {'id': 'cartform'}).find_all('input'):
                if str(prop.get('name')) == 'terms':
                    cart_proceed['terms'] = 'on'
                elif str(prop.get('name')) != 'checkout':
                    cart_proceed[str(prop.get('name'))] = str(prop.get('value'))
        except:
            print('No cart form found, proceeding')
        self.status_signal.emit({"msg": "Posting checkout", "status": "normal"})
        checkout_post = self.session.post(f'{self.main_site}cart', data=cart_proceed, headers=self.request_headers(self.main_site))
        self.session_to_browser()
        if 'checkouts/' not in checkout_post.url:
            self.handle_checkpoint(checkout_post.url)
        else:
            self.status_signal.emit({"msg": "Waiting for auth token", "status": "normal"})
            self.main_url = checkout_post.url

    # This portion monitors for the item and will add to cart when it can
    def monitor(self):
        variant = ''
        found = False
        while True:
            try:
                if variant == '':
                    # This runs only on first loop.
                    if not found:
                        self.status_signal.emit({"msg": "Searching for product", "status": "checking"})
                    elif found:
                        self.status_signal.emit({"msg": "Checking stock", "status": "checking"})
                    # Gets item data from product.json endpoint.
                    products = self.session.get(self.main_site + 'products.json?limit=250')
                    # Only operates when a valid response happens
                    if products.status_code == 200:
                        # List of all products is stores as json
                        products = products.json()['products']
                        # Loops through all products in json
                        for prod in products:
                            # Filters by item handle (text after 'product/' in URL)
                            self.title = prod['title']
                            # The handle on the product matches the stored in the bot
                            if self.compare_kw(self.title, self.product_kws):
                                if not found:
                                    found = True
                                    self.product_signal.emit(self.title)
                                    self.handle = prod['handle']
                                    threading.Thread(target=self.change_driver, args=[f"{self.main_site}products/{self.handle}"]).start()
                                # Saves product image
                                self.image = prod['images'][0]['src']
                                # Now we loop through variants. You can think of these as different options for the product
                                # If an item as one size, it goes by Default Title.
                                # We need to do this as UK sites tend to have one "Raspberry Pi 4" page with the different RAM models as different variants
                                # US sites tend to have one separate item page per Pi 4.
                                if self.size_kw == '':
                                    if len(prod['variants']) == 1:
                                        one_var = prod['variants'][0]
                                        if one_var['available']:
                                            self.variant = one_var['id']
                                            self.size_label = one_var['title']
                                            self.product_signal.emit(f"{self.title} / {self.size_label}")
                                            return
                                        else:
                                            self.status_signal.emit({"msg": "Size OOS (One size)", "status": "monitoring"})
                                            # If product is not available, sleep for delay and try again. Rotates proxy if you use them
                                            self.update_random_proxy()
                                            time.sleep(float(self.monitor_delay))
                                    else:
                                        vars = []
                                        for vr in prod['variants']:
                                            if vr['available']:
                                                vars.append(vr)
                                        if len(vars) > 0:
                                            rand = random.choice(vars)
                                            self.size_label = rand['title']
                                            self.product_signal.emit(f"{self.title} / {self.size_label}")
                                            self.variant = rand['id']
                                            return
                                        else:
                                            self.status_signal.emit(
                                                {"msg": "Waiting for any size to restock", "status": "monitoring"})
                                            # If product is not available, sleep for delay and try again. Rotates proxy if you use them
                                            self.update_random_proxy()
                                            time.sleep(float(self.monitor_delay))
                                else:
                                    size_found = False
                                    for vr in prod['variants']:
                                        # If the variant name contains the size stored in bot.
                                        if self.compare_size(vr['title']):
                                            size_found = True
                                            # If the variants "available" tag is true, it is in stock
                                            # This is how Pi Helper monitors these sites, by checking this tag on products!
                                            if vr['available']:
                                                # Stores variant to 'variant' variable. Exits monitoring loop
                                                self.variant = vr['id']
                                                self.size_label = vr['title']
                                                self.product_signal.emit(f"{self.title} / {self.size_label}")
                                                return
                                            else:
                                                self.status_signal.emit({"msg": "Size OOS", "status": "monitoring"})
                                                # If product is not available, sleep for delay and try again. Rotates proxy if you use them
                                                self.update_random_proxy()
                                                time.sleep(float(self.monitor_delay))
                                    if not size_found:
                                        self.status_signal.emit({"msg": "Size not found", "status": "monitoring"})
                                        # If product is not available, sleep for delay and try again. Rotates proxy if you use them
                                        self.update_random_proxy()
                                        time.sleep(float(self.monitor_delay))
                                    # Since we found the handle, no need to check the other products. End loop early
                                break
                        # If product is NOT found (this shouldn't happen unless site change), sleep and try to find again
                        if not found:
                            self.status_signal.emit({"msg": "Waiting for product", "status": "monitoring"})
                            self.update_random_proxy()
                            time.sleep(float(self.monitor_delay))
                    elif products.status_code == 430:
                        # 430 is the response code when rate limited. Sleep for error delay and try again
                        self.status_signal.emit({"msg": f'IP Rate Limited!', "status": "error_no_log"})
                        self.update_random_proxy()
                        time.sleep(float(self.error_delay))
                    else:
                        # Sleep for error delay and try again
                        self.status_signal.emit({"msg": f'Error getting stock [{products.status_code}]', "status": "error"})
                        self.update_random_proxy()
                        time.sleep(float(self.error_delay))

            except Exception:
                print(traceback.format_exc())
                self.status_signal.emit({"msg": "Queue is up", "status": "error"})
                while 'checkout/' not in self.driver.current_url:
                    time.sleep(1)
                for cookie in self.driver.get_cookies():
                    self.session.cookies.set(cookie['name'], cookie['value'], domain=cookie['domain'],
                                             path=cookie['path'])

    # This function returns auth token and shipping rate
    # Shipping rate is the shipping method used during checkout
    def get_tokens(self,req):
        profile = self.profile
        try:
            # This uses a neat cart URL to load all shipping methods for the items in your cart.
            # It will choose the first one (cheapest method)
            self.status_signal.emit({"msg": "Getting Shipping Rates", "status": "normal"})
            jayson = self.session.get(f'{self.main_site}cart/shipping_rates.json?shipping_address[zip]={str(profile["shipping_zipcode"]).replace(" ","")}&shipping_address[country]={get_country_code(profile["shipping_country"])}&shipping_address[province]={profile["shipping_state"]}').json()
            if len(jayson['shipping_rates']) == 0:
                return ''
            full_rate = f'{jayson["shipping_rates"][0]["source"]}-{jayson["shipping_rates"][0]["code"]}-{jayson["shipping_rates"][0]["price"]}'
        except:
            # Prints shipping rate json on failed fetch (for logging)
            self.status_signal.emit({"msg": "Error Fetching Shipping Rate", "status": "error"})
            print(f'Shipping rate response -> {jayson}')
            return ''

    def get_manual_rate(self):
        self.status_signal.emit({"msg": "Waiting for shipping rates", "status": "normal"})
        while True:
            manual_rate_get = self.session.get(f"{self.main_url}?previous_step=contact_information&step=shipping_method")
            soup = BeautifulSoup(manual_rate_get.content, 'html.parser')
            if 'This order can’t be shipped to the address you entered' in manual_rate_get.text:
                self.status_signal.emit({"msg": "Item can't be shipped to address", "status": "error"})
                return
            if 'and the items you added can’t be shipped to your address' in manual_rate_get.text:
                self.status_signal.emit({"msg": "Item can't be shipped to address", "status": "error"})
                return
            for radio_button in soup.find_all('div', {'class': 'radio-wrapper'}):
                if radio_button.has_attr('data-shipping-method'):
                    self.shipping_rate = radio_button.get('data-shipping-method')
                    print(f'Found Rate -> {self.shipping_rate}')
                    return
            time.sleep(1)
    # Here we handle the shipping details (first page on Shopify checkout)
    def submit_shipping(self):
        while True:
            try:
                profile = self.profile
                # This is the data you send when submitting shipping details
                x = {'_method': 'patch',
                     'authenticity_token': self.auth_token,
                     'previous_step': 'contact_information',
                     'step': 'shipping_method',
                     'checkout[buyer_accepts_marketing]': '1',
                     'checkout[shipping_address][first_name]': profile['shipping_fname'],
                     'checkout[shipping_address][last_name]': profile['shipping_lname'],
                     'checkout[shipping_address][address1]': profile['shipping_a1'],
                     'checkout[shipping_address][address2]': profile['shipping_a2'],
                     'checkout[shipping_address][city]': profile['shipping_city'],
                     'checkout[shipping_address][country]': profile['shipping_country'],
                     'checkout[shipping_address][zip]': profile['shipping_zipcode'],
                     'checkout[shipping_address][phone]': self.format_phone2(profile["shipping_phone"]),
                     'checkout[email]': profile['shipping_email'],
                     'checkout[client_details][browser_width]': '1009',
                     'checkout[client_details][browser_height]': '947',
                     'checkout[client_details][javascript_enabled]': '1',
                     'checkout[client_details][color_depth]': '24',
                     'checkout[client_details][java_enabled]': 'false',
                     'checkout[client_details][browzer_tz]': '300'
                     }
                state = str(profile['shipping_state'])
                # Adds shipping state ONLY if your profile has a state.
                if state != '':
                    x.update({'checkout[shipping_address][province]': state})
                self.status_signal.emit({"msg": "Submitting Shipping Info", "status": "normal"})
                # Sends data to appropriate URL.
                self.session.post(self.main_url,data=x, headers=self.request_headers(self.main_url + '?step=contact_information'))
                return
            except:
                self.status_signal.emit({"msg": "Error Submitting Shipping", "status": "error"})
                time.sleep(float(self.error_delay))

    # This is where we submit the shipping rate obtained above. This is the second page in the checkout process
    def submit_rates(self):
       self.get_manual_rate()
       while True:
           try:
               # This is the data sent on submitting shipping rate
               # A majority of sites will use the rate, but with spaces replaced with '%20'
                rate_data = {'_method': 'patch',
                             'authenticity_token': self.auth_token,
                     'previous_step': 'shipping_method',
                     'step': 'payment_method',
                     'checkout[shipping_rate][id]': str(self.shipping_rate).replace(" ", '%20'),
                     'checkout[client_details][browser_width]': '1009',
                     'checkout[client_details][browser_height]': '947',
                     'checkout[client_details][javascript_enabled]': '1',
                     'checkout[client_details][color_depth]': '24',
                     'checkout[client_details][java_enabled]': 'false',
                     'checkout[client_details][browzer_tz]': '240'
                     }
                self.status_signal.emit({"msg": "Submitting Shipping Rate", "status": "normal"})
                # Sends data to appropriate URL.
                r = self.session.post(self.main_url, headers=self.request_headers(self.main_url + '?previous_step=shipping_method&step=payment_method'), data=rate_data, allow_redirects=True)
                # If it doesn't work, it will try again but with the unformatted rate
                if not 'step=payment_method' in r.url:
                    x = {'_method': 'patch',
                         'authenticity_token': '',
                         'previous_step': 'shipping_method',
                         'step': 'payment_method',
                         'checkout[shipping_rate][id]': str(self.shipping_rate),
                         'checkout[client_details][browser_width]': '1009',
                         'checkout[client_details][browser_height]': '947',
                         'checkout[client_details][javascript_enabled]': '1',
                         'checkout[client_details][color_depth]': '24',
                         'checkout[client_details][java_enabled]': 'false',
                         'checkout[client_details][browzer_tz]': '240'
                         }
                    self.status_signal.emit({"msg": "Submitting Shipping Rate (Alt)", "status": "normal"})
                    r2 = self.session.post(self.main_url, headers=self.request_headers(f'{self.main_url}?previous_step=shipping_method&step=payment_method'), data=x, allow_redirects=True)
                    # Checks if alt rate worked
                    if 'step=payment_method' in r2.url:
                        return
                    elif 'Your cart has been updated' in r.text:
                        if 'and the items you added can’t be shipped to your address' in r.text:
                            self.status_signal.emit({"msg": "Item can't be shipped", "status": "error"})
                            return
                        self.get_manual_rate()
                    else:
                        # Tries again (can be a site error)
                        self.status_signal.emit({"msg": "Error submitting rates", "status": "error"})
                        for cookie in self.session.cookies:
                            self.driver.add_cookie({'name': cookie.name, 'value': cookie.value, 'path': cookie.path, 'domain': cookie.domain})
                        time.sleep(float(self.error_delay))
                else:
                    # If first rate submit works, proceed
                    return
           except Exception as e:
               self.status_signal.emit({"msg": "Error submitting rates", "status": "error"})
               print(traceback.format_exc())
               time.sleep(float(self.error_delay))

    # This will calculate taxes, and returns full price and gateway ID (needed for payment)
    def calc_taxes(self):
        # Just parses page
        self.status_signal.emit({"msg": "Calculating Tax", "status": "normal"})
        while True:
            try:
                rate_after = self.session.get(f'{self.main_url}?step=payment_method', allow_redirects=True)
                if 'gateway' in rate_after.text:
                    price = self.get_price(rate_after.text)
                    gateway = self.get_gateway(rate_after.text)
                    return price,gateway
                else:
                    time.sleep(1)
            except:
                # If theres an error, it will try again after error delay
                self.status_signal.emit({"msg": "Error Calculating Tax", "status": "error"})
                print(rate_after.text)
                print(traceback.format_exc())
                time.sleep(float(self.error_delay))

    # Now we submit payment. This is the third and final page of the checkout process.
    def submit_payment(self):
        # We must encrypt the payment using Shopify's checkout.shopifycs.com.
        self.status_signal.emit({"msg": "Encrypting Payment", "status": "normal"})
        profile = self.profile
        url_to_use = self.main_site.replace("https://", '').replace('www.', '')
        # Loads your card details into a json
        cs = '{"credit_card":{"number":"' + profile["card_number"] + '","name":"' + f'{profile["shipping_fname"]} {profile["shipping_lname"]}' + '","month":' + str(int(profile["card_month"])) + ',"year":' + profile["card_year"] + ',"verification_value":"' + profile["card_cvv"] + '"}, "payment_session_scope": "' + url_to_use + '"}'
        card_payload = str(cs).replace('\n', '')

        # Headers for encryption
        shopify_cs_headers = {
            'Content-Type': 'application/json',
            'Accept': 'application/json',
            'Origin': 'https://checkout.shopifycs.com',
            'Sec-Fetch-Site': 'same-site',
            'Sec-Fetch-Mode': 'cors',
            'Sec-Fetch-Dest': 'empty',
            'Referer': 'https://checkout.shopifycs.com/'

        }
        # Sends card data for encryption
        encrypt = self.session.post('https://deposit.us.shopifycs.com/sessions', headers=shopify_cs_headers, data=card_payload, verify=False)
        # Returns an encrypted ID for your details
        encrypt_info = encrypt.json()['id']

        # This is the data sent on submitting payment
        pay_data = {'_method': 'patch',
             'authentication_token': self.auth_token,
             'previous_step': 'payment_method',
             'step': '',
             's': encrypt_info,
             'checkout[payment_gateway]': self.gateway,
             'checkout[credit_card][vault]': 'false',
             'checkout[different_billing_address]': 'false',
             'checkout[vault_phone]': self.format_phone(profile['shipping_phone']),
             'checkout[total_price]': self.price,
             'complete': '1',
             'checkout[client_details][browser_width]': '1009',
             'checkout[client_details][browser_height]': '947',
             'checkout[client_details][javascript_enabled]': '1',
             'checkout[client_details][color_depth]': '24',
             'checkout[client_details][java_enabled]': 'false',
             'checkout[client_details][browzer_tz]': '240'
             }
        self.status_signal.emit({"msg": "Submitting Payment", "status": "normal"})
        # Sends data to payment URL.
        submit = self.session.post(self.main_url, allow_redirects=True, headers=self.request_headers(self.main_url),data=pay_data)
        # If processing or authentications is in the URL, payment has been submitted.
        if ('processing' in submit.url) or 'authentications' in submit.url:
            self.status_signal.emit({"msg": "Processing", "status": "alt"})
            pay_url = submit.url + "?from_processing_page=1"
            while True:
                # Poll the processing/authentication URL
                after = self.session.get(pay_url, allow_redirects=True)
                # Sometimes, when Shopify sites are busy you'll just get a "Thank you for your order" page and it might be a checkout.
                # I've only really seen this in testing with PiHut
                if 'Thanks for your order' in after.text:
                    break
                # PiHut authentication handling. Fun stuff
                if 'authentications' in after.url:
                    # Auth key is just the key at the end of the URL.
                    keys = after.url.split("/")
                    cardinal_key = keys[len(keys)-1]
                    num_of_checks = 1
                    is_202 = False
                    self.status_signal.emit({"msg": f"Handling UK Auth", "status": "alt"})
                    while True:
                        self.status_signal.emit({"msg": f"Handling UK Auth ({num_of_checks})", "status": "alt_no_log"})
                        # Polls the authentication URL. It will give a 202 response code when authenticating,
                        # and a 200 response code when it has passed authentication
                        auth_get = self.session.get(f'{after.url.split("?")[0]}/poll?authentication={cardinal_key}')

                        # If it does have a 202 error code, set is_202 to True
                        if auth_get.status_code == 202 and not is_202:
                            is_202 = True
                        elif auth_get.status_code == 200 and is_202:
                            # Authentication has passed
                            break
                        elif num_of_checks >= 5 and not is_202:
                            # If it doesn't read a 202 response in 5 times, it will retry.
                            self.status_signal.emit({"msg": f"Retrying Auth", "status": "alt_no_log"})
                            auth_get = self.session.get(after.url.split("?")[0])
                            break
                        else:
                            # Increment num of checks and sleep
                            num_of_checks +=1
                            time.sleep(1)

                    # Only happens if you exit loop and you at one point read a 202
                    if is_202:
                        self.status_signal.emit({"msg": "Processing (Passing Auth)", "status": "alt"})
                        # Now we can go to the auth URL and it will redirect to processing
                        after = self.session.get(f'{auth_get.url}?')
                        if '/processing' in after.url:
                            # Processing. This is when you see the wheel spinning and it says "Processing"
                            self.status_signal.emit({"msg": "Processing", "status": "alt"})
                            base_url = after.url
                            while True:
                                pay_url = base_url + "?from_processing_page=1"
                                # Polls processing page
                                after = self.session.get(pay_url)
                                if '/processing' in after.url:
                                    time.sleep(1)
                                else:
                                    # Processing is done. Exit poll loop
                                    break

                elif '/processing' in after.url:
                    # Processing is not done. Stay in poll loop
                    time.sleep(1)
                else:
                    # Processing is done. Exit poll loop
                    break
            checkout_time = time.time() - self.start
            if '&validate=true' in after.url:
                # This means the checkout was unsuccessful.
                price_to_use = int(self.price)/100
                self.status_signal.emit({"msg": "Checkout Failed", "status": "error"})
                failed_web(after.url,self.image,f'{self.main_site}', f"{self.title} / {self.size_label}",self.profile["profile_name"], "{:.2f}".format(price_to_use),checkout_time)

            elif 'thank_you' in after.url:
                # This means the checkout was successful.
                price_to_use = int(self.price)/100
                self.status_signal.emit({"msg": "Successful Checkout", "status": "success"})
                good_web(after.url, self.image, f'{self.main_site}',
                         f"{self.title} / {self.size_label}", self.profile["profile_name"],
                       "{:.2f}".format(price_to_use),checkout_time)

            else:
                # Sometimes there can be weird URLs after submitting order.
                self.status_signal.emit({"msg": "Checking order", "status": "alt"})
                price_to_use = int(self.price)/100
                r = self.session.get(self.main_url + "/thank_you")
                if r.url.endswith('/processing'):
                    # IDK there is some weird processing thing that this handles. It happened one time I think
                    self.status_signal.emit({"msg": "Checking order (Processing)", "status": "alt"})
                    while True:
                        time.sleep(2)
                        r = self.session.get(r.url)
                        if not r.url.endswith('/processing'):
                            break
                # If it shows up with "order" in URL, it is a good checkout.
                if 'order' in r.url or 'thank_you' in r.url:
                    self.status_signal.emit({"msg": "Successful Checkout", "status": "success"})
                    if self.settings['webhooksuccess']:
                        good_web(r.url, self.image, f'{self.main_site}',
                                 f"{self.title} / {self.size_label}", self.profile["profile_name"],
                                 "{:.2f}".format(price_to_use), checkout_time)
                else:
                    # Checkout failed.
                    self.status_signal.emit({"msg": "Checkout Failed", "status": "error"})
                    if self.settings['webhookfail']:
                        failed_web(r.url, self.image, f'{self.main_site}',  f"{self.title} / {self.size_label}",
                                   self.profile["profile_name"], "{:.2f}".format(price_to_use), checkout_time)
        else:
            # Other error checking out
            print(submit.url)
            print(submit.text.replace('\n', ''))
            price_to_use = int(self.price) / 100
            failed_web(submit.url, self.image, f'{self.main_site}',  f"{self.title} / {self.size_label}",
                       self.profile["profile_name"], "{:.2f}".format(price_to_use), 1)
    def handle_checkpoint(self, url):
        self.driver.get(url)
        while 'checkouts/' not in self.driver.current_url:
            if 'checkpoint' in self.driver.current_url:
                self.status_signal.emit({"msg": "Solve checkpoint", "status": "alt"})
                while 'checkpoint' in self.driver.current_url:
                    time.sleep(0.25)
            if 'throttle' in self.driver.current_url:
                self.status_signal.emit({"msg": "In queue", "status": "alt"})
                while 'throttle' in self.driver.current_url:
                    time.sleep(0.25)
            if '/cart' in self.driver.current_url:
                if 'your shopping cart is empty' in str(self.driver.page_source).lower():
                    self.status_signal.emit({"msg": "Redirecting to item", "status": "normal"})
                    self.driver.get(self.main_site + 'products/' + self.handle)
                    self.status_signal.emit({"msg": "Cart manually, go to checkout", "status": "alt"})
                    while 'checkouts/' not in self.driver.current_url:
                        time.sleep(0.5)
                else:
                    self.status_signal.emit({"msg": "Navigate to checkout", "status": "alt"})
                    while 'checkouts/' not in self.driver.current_url:
                        time.sleep(0.5)

        self.browser_to_session()
        self.main_url = self.driver.current_url

    # These are the headers used during the whole process, with a field to change the referer URL.
    def request_headers(self, url):
        x = {'Content-Type': 'application/x-www-form-urlencoded',
             "Accept": 'application/json, text/javascript, */*; q=0.01',
             'sec-fetch-site': 'same-origin',
             'sec-fetch-mode': 'navigate',
             'sec-fetch-user': '?1',
             'sec-fetch-dest': 'document',
             'sec-ch-ua-mobile': '?0',
             'accept-encoding': 'gzip, deflate',
             'cache-control': 'max-age=0',
             'upgrade-insecure-requests': '1',
             'dnt': '1',
             'referer': url
             }
        return x

    # Method to determine if the variant is the one we want to parse.
    def compare_size(self,title):
        if self.size_kw == '':
            return True
        item_comp = title.lower()
        for keyword in self.size_kw.split(' '):
            kw = str(keyword).lower()
            if '-' in keyword:
                if kw[1::] in item_comp:
                    return False
            else:
                if kw not in item_comp:
                    return False
        return True

    # Method to update proxy to random one in list
    def update_random_proxy(self):
        if self.proxy_list != False:
            proxy_to_use = format_proxy(random.choice(self.proxy_list))
            self.session.proxies.update(proxy_to_use)

    def change_driver(self, url):
        self.driver.get(url)


