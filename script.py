import asyncio
from playwright.async_api import async_playwright
import logging
import os
from googlesearch import search

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

good_listings = []
listings = []
KEYWORDS = []

async def reverse_image_search(image_url, context):
    page = None
    try:
        results = []
        page = await context.new_page()
        await page.goto('https://images.google.ca')
        await page.click('div[aria-label="Search by image"]')
        await page.fill('input[placeholder="Paste image link"]', image_url)
        await page.click('input[placeholder="Paste image link"]')
        await page.keyboard.press('Enter')
        await page.wait_for_load_state('networkidle')
        links = await page.query_selector_all('a')
        for link in links:
            href = await link.get_attribute('href')
            if href:
                results.append(str(href))
        for result in results:
            if "https://reverb.com/ca/item" in result:
                return result
        return False
    finally:
        if page:
            await page.close()

with open('keywords.txt', 'r') as f:
    for line in f:
        KEYWORDS.append(line.strip())


async def login_to_facebook():
    p = await async_playwright().start()
    logger.info("Launching browser...")
    browser = await p.chromium.launch(headless=False)
    
    logger.info("Creating new context...")
    context = await browser.new_context()
    
    logger.info("Opening new page...")
    page = await context.new_page()
    
    logger.info("Navigating to Facebook...")
    await page.goto('https://www.facebook.com/')
    
    fb_username = os.getenv('FBUSER')
    fb_password = os.getenv('FBPASS')
    
    if not fb_username or not fb_password:
        raise ValueError("Facebook credentials not found in environment variables")
    
    # Fill in login form
    await page.fill('input[name="email"]', fb_username)
    await page.fill('input[name="pass"]', fb_password)
    
    # Click login button
    await page.click('button[name="login"]')
    
    # Wait for navigation
    await page.wait_for_load_state('networkidle')
    
    await page.goto('https://www.facebook.com/marketplace/category/electric-guitars')
    await page.wait_for_load_state('networkidle')
    
    return page, browser, context, p

async def scrape_listings(page):
    try:
        listings_count = 0
        while len(listings) < 500:
            logger.info(f"Current listings count: {len(listings)}")
            
            await page.wait_for_selector('div[role="main"]', timeout=30000)
            listing_elements = await page.query_selector_all('div[role="main"] > div > div > div > div > div > div[style]')
            
            if not listing_elements:
                break
                
            for listing in listing_elements:
                if len(listings) >= 500:
                    break
                try:
                    img_elements = await listing.query_selector_all('img')
                    imgs = [await img.get_attribute('src') for img in img_elements if await img.get_attribute('src')]
                    
                    text_element = await listing.query_selector('div[class*="xyqdw3p x4uap5 xjkvuk6 xkhd6sd"]')
                    txt = await text_element.text_content() if text_element else ''
                    
                    link_element = await listing.query_selector('a')
                    lnk = await link_element.get_attribute('href') if link_element else ''
                    
                    price_element = await listing.query_selector('span[dir="auto"]')
                    price = await price_element.inner_text() if price_element else ''
                    price = ''.join(char for char in price if char.isdigit() or char == '.')
                    
                    if imgs and txt and lnk:
                        # Get cleaned text
                        cleaned_txt = clean_text(txt)
                        
                        listing_dict = {
                            'imgs': imgs,
                            'txt': cleaned_txt,
                            'lnk': "https://www.facebook.com" + lnk,
                            'price': float(price),
                            'reverb': None
                        }
                        listings.append(listing_dict)
                
                except Exception as e:
                    continue
            
            await page.evaluate('window.scrollTo(0, document.body.scrollHeight)')
            await page.wait_for_timeout(700)
            
            if listings_count == len(listings):
                break
            listings_count = len(listings)
    except Exception as e:
        logger.error(f"Scraping error: {str(e)}")
        raise

def clean_text(text):
    # Convert text to lowercase and remove punctuation
    text = ''.join(char for char in text if char.isalnum() or char.isspace())
    
    # Split text into words and only keep words that are in keywords, contain numbers, or were originally capitalized
    words = text.split()
    filtered_words = []
    for word in words:
        # Skip any word starting with 'ca'
        if word[:2].lower() == 'ca' or word.lower() in ['electric', 'guitar', 'beginner', 'amp', 'starter', 'kit', 'case']:
            continue
            
        # Allow word if it has digits or is uppercase, but not if it's 'electric' or 'guitar'
        if any(char.isdigit() for char in word) or word[0].isupper():
            filtered_words.append(word.lower())
    filtered_words = list(set(filtered_words))  # Remove duplicates
    
    # Join filtered words back together
    return ' '.join(filtered_words)

async def search_google(listing, context):
    wordcount = len(listing['txt'].split())
    if wordcount >= 3:
        results = list(search(listing['txt'] + " reverb", stop=5, num=5))
        for result in results:
            if "https://reverb.com/ca/item" in result:
                listing['reverb'] = result
                return result
    else:
        if listing['price'] > 200:
            try:
                listing['reverb'] = await reverse_image_search(listing['imgs'][0], context)
                return listing['reverb']
            except Exception as e:
                logger.error(f"Reverse image search error: {str(e)}")
    listing['reverb'] = False
    return False

async def price_test(listing, context):
    page = None
    try:
        reverblink = await search_google(listing, context)
        if not reverblink:
            return False
        page = await context.new_page()
        await page.goto(reverblink)
        
        # Use query_selector with timeout instead of wait_for_selector
        price_element = await page.wait_for_selector('.price-with-shipping__price__amount', timeout=10000)
        if price_element:
            price_text = await price_element.text_content()
            resell = ''.join(char for char in price_text if char.isdigit() or char == '.')
            try:
                resell = float(resell)
                listing['resell'] = resell
                if (resell*.4)-50 >= listing['price']:
                    good_listings.append(listing)
            except ValueError:
                resell = None
    except:
        return False
    finally:
        if page:
            await page.close()

async def main():
    logger.info("Starting Facebook Marketplace scraper...")
    try:
        page, browser, context, p = await login_to_facebook()
        try:
            await scrape_listings(page)
        finally:
            await page.close()
    except Exception as e:
        logger.error(f"Fatal error: {str(e)}")
        return  # Exit if we can't even scrape
    
    logger.info(f"Scraping complete. Total listings: {len(listings)}")
    
    # Process all listings concurrently for efficiency (optional)
    # await asyncio.gather(*[price_test(listing, context) for listing in listings])
    
    # Or process sequentially if you prefer
    for listing in listings:
        await price_test(listing, context)
    
    # Close first browser session
    await context.close()
    await browser.close()
    
    # Open results in new browser
    results = await p.chromium.launch(headless=False)
    context2 = await results.new_context()
    
    print(f"Opening {len(good_listings)} good listings...")
    for listing in good_listings:
        marketplace = await context2.new_page()
        await marketplace.goto(listing['lnk'])
        reverb = await context2.new_page()
        await reverb.goto(listing['reverb'])
    
    try:
        print("Press Ctrl+C to close browsers and exit")
        await asyncio.Event().wait()
    except KeyboardInterrupt:
        await context2.close()
        await results.close()
        await p.stop()

if __name__ == "__main__":
    asyncio.run(main())