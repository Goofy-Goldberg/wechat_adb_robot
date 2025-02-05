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
    return open({
        filename: 'articles.db',
        driver: sqlite3.Database
    });
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
    const now = Date.now() / 1000; // Convert to Unix timestamp
    await db.run(`
        UPDATE articles 
        SET content = ?, 
            author = ?, 
            publish_time = ?,
            scraped_at = ?
        WHERE url = ?
    `, [
        articleData.content,
        articleData.author,
        articleData.publishTime,
        now,
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

        // Wait for the content to be available
        await page.waitForFunction('window.cgiData !== undefined', { timeout: 10000 })
            .catch(e => console.log('Warning: cgiData not found after timeout'));

        console.log('Evaluating page content...');
        const articleData = await page.evaluate(() => {
            console.log('Inside page.evaluate');
            const data = window.cgiData || {};
            console.log('cgiData:', JSON.stringify(data));
            debugger;
            return {
                title: data.title,
                author: data.author,
                content: data.content,
                publishTime: data.publishTime,
                originalUrl: window.location.href,
            };
        });

        console.log('Article data extracted:', articleData);

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