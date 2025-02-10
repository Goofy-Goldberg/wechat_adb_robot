const puppeteer = require('puppeteer-extra');
const StealthPlugin = require('puppeteer-extra-plugin-stealth');
const UserAgent = require('user-agents');
const sqlite3 = require('sqlite3');
const { open } = require('sqlite');
const dotenv = require('dotenv');

dotenv.config();

puppeteer.use(StealthPlugin());

// Database setup
async function getDb() {
    const db = await open({
        filename: 'articles.db',
        driver: sqlite3.Database
    });

    // Add metadata column if it doesn't exist
    try {
        await db.get('SELECT metadata FROM articles LIMIT 1');
    } catch (error) {
        if (error.message.includes('no such column')) {
            await db.exec('ALTER TABLE articles ADD COLUMN metadata TEXT');
        }
    }

    return db;
}

async function getUnscrapedArticles(db) {
    return db.all(`
        SELECT url, title 
        FROM articles 
        WHERE content IS NULL 
        ORDER BY published_at DESC
        LIMIT 10
    `);        // AND scraped_at IS NULL

}

async function updateArticleContent(db, url, articleData) {
    const now = Date.now() / 1000;
    
    // Separate core fields from metadata
    const {
        title,
        author,
        content,
        publishTime,
        url: originalUrl,
        // Fields that will go into metadata
        description,
        ogImage,
        biz,
        sn,
        mid,
        idx,
        ...otherFields
    } = articleData;

    // Construct metadata object
    const metadata = {
        description,
        ogImage,
        biz,
        sn,
        mid,
        idx,
        ...otherFields
    };

    await db.run(`
        UPDATE articles 
        SET content = ?, 
            author = ?, 
            published_at = ?,
            scraped_at = ?,
            metadata = ?
        WHERE url = ?
    `, [
        content,
        author,
        publishTime,
        now,
        JSON.stringify(metadata),
        url
    ]);
}

async function scrapeArticle(url) {
    console.log(`Scraping article: ${url}`);
    const browser = await puppeteer.launch({
        headless: false,
        args: [
            '--no-sandbox',
            '--disable-setuid-sandbox',
            '--disable-dev-shm-usage',
            '--disable-gpu'
        ],
        defaultViewport: { width: 1920, height: 1080 },
        executablePath: process.env.CHROME_PATH || '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome'
    });

    try {
        console.log('Browser launched');
        const page = await browser.newPage();
        console.log('New page created');
        
        // Enable console log from the page
        page.on('console', msg => console.log('PAGE LOG:', msg.text()));
        
        await page.setUserAgent(new UserAgent().toString());
        console.log('User agent set');

        // Add request interception for debugging
        await page.setRequestInterception(true);
        page.on('request', request => {
            console.log(`Request: ${request.url()}`);
            request.continue();
        });

        console.log('Navigating to URL...');
        const response = await page.goto(url, { 
            waitUntil: 'networkidle0',
            timeout: 30000 
        });
        console.log('Page loaded with status:', response.status());

        console.log('Evaluating page content...');
        const articleData = await page.evaluate(() => {
            console.log('Inside page.evaluate');
            
            function getPublishDate() {
                // Try visible publish time first
                const publishTimeElement = document.querySelector("#publish_time");
                if (publishTimeElement) {
                    const timeText = publishTimeElement.textContent.trim();
                    // Parse Chinese format: 2025年01月30日 08:19
                    const match = timeText.match(/(\d{4})年(\d{2})月(\d{2})日\s*(\d{2}):(\d{2})/);
                    if (match) {
                        const [_, year, month, day, hours, minutes] = match;
                        // Create a date object in local timezone
                        const localDate = new Date(year, month - 1, day, hours, minutes);
                        // Convert to UTC timestamp in seconds
                        return Math.floor(localDate.getTime() / 1000);
                    }
                    return null; // Return null if parsing fails
                }

                // If not visible, try to get from script
                const script = document.querySelector('script[nonce][reportloaderror]');
                if (script && script.textContent) {
                    const match = script.textContent.match(/var create_time = "(\d+)" \* 1;/);
                    if (match && match[1]) {
                        const timestamp = parseInt(match[1], 10);
                        if (!isNaN(timestamp)) {
                            return timestamp; // This is already a UTC timestamp
                        }
                    }
                }
                return null;
            }

            function getMetaData() {
                const scriptElements = document.querySelectorAll('script[nonce][reportloaderror]');
                const metaData = {
                    biz: null,
                    sn: null,
                    mid: null,
                    idx: null
                };

                scriptElements.forEach(script => {
                    if (script.textContent.includes("var biz =") && script.textContent.includes("var sn =")) {
                        const bizMatch = script.textContent.match(/var biz = "([^"]*)"/);
                        if (bizMatch) metaData.biz = bizMatch[1];
                        
                        const snMatch = script.textContent.match(/var sn = "([^"]*)"/);
                        if (snMatch) metaData.sn = snMatch[1];
                        
                        const midMatch = script.textContent.match(/var mid = "([^"]*)"/);
                        if (midMatch) metaData.mid = midMatch[1];
                        
                        const idxMatch = script.textContent.match(/var idx = "([^"]*)"/);
                        if (idxMatch) metaData.idx = idxMatch[1];
                    }
                });

                return metaData;
            }

            // Get content with better error handling
            const contentElement = document.querySelector("#js_content");
            const content = contentElement ? contentElement.textContent.trim() : null;

            // Get title with better error handling
            const titleElement = document.querySelector("#activity-name");
            const title = titleElement ? titleElement.textContent.trim() : null;

            // Get author with better error handling
            const authorElement = document.querySelector("#js_name");
            const author = authorElement ? authorElement.textContent.trim() : null;

            // Get description
            const descriptionElement = document.querySelector('meta[name="description"]');
            const description = descriptionElement ? descriptionElement.getAttribute("content") : null;

            // Get og:image
            const ogImageElement = document.querySelector('meta[property="og:image"]');
            const ogImage = ogImageElement ? ogImageElement.getAttribute("content") : null;

            const publishTime = getPublishDate();
            const metaData = getMetaData();

            console.log('Extracted data:', { title, author, publishTime, content: content?.substring(0, 100) + '...' });

            return {
                title,
                author,
                content,
                publishTime,
                description,
                ogImage,
                ...metaData,
                originalUrl: window.location.href,
            };
        });

        console.log('Article data extracted:', {
            ...articleData,
            content: articleData.content?.substring(0, 100) + '...' // Only log first 100 chars of content
        });

        // Connect to database and update the article
        const db = await getDb();
        await updateArticleContent(db, url, articleData);
        await db.close();

        console.log('Successfully scraped and updated article:', articleData.title);
        return articleData;

    } catch (error) {
        console.error(`Error scraping article ${url}:`, error.message);
        console.error('Full error:', error);
        // Mark the article as failed to scrape
        const db = await getDb();
        await db.run(`
            UPDATE articles 
            SET scraped_at = ?
            WHERE url = ?
        `, [Date.now() / 1000, url]);
        await db.close();
        throw error;
    } finally {
        await browser.close();
    }
}

async function scrapeAllPendingArticles() {
    const db = await getDb();
    const articles = await getUnscrapedArticles(db);
    await db.close();

    if (articles.length === 0) {
        console.log('No pending articles to scrape');
        return;
    }

    console.log(`Found ${articles.length} articles to scrape`);
    
    for (const article of articles) {
        try {
            await scrapeArticle(article.url);
            // Add a small delay between requests to avoid overwhelming the server
            await new Promise(resolve => setTimeout(resolve, 2000));
        } catch (error) {
            console.error(`Failed to scrape article ${article.url}:`, error.message);
            // Continue with next article even if one fails
            continue;
        }
    }
}

// Main execution
const articleUrl = process.argv[2];
if (articleUrl) {
    // Scrape specific URL if provided
    scrapeArticle(articleUrl)
        .catch(error => {
            console.error('Error scraping article:', error);
            process.exit(1);
        });
} else {
    // Otherwise scrape all pending articles
    scrapeAllPendingArticles()
        .catch(error => {
            console.error('Error in batch scraping:', error);
            process.exit(1);
        });
} 