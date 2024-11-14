import re
import time
import json
import numpy as np
import pandas as pd
from tqdm import tqdm
from datetime import datetime

from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.support.ui import WebDriverWait
from webdriver_manager.chrome import ChromeDriverManager
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import NoSuchElementException, TimeoutException, StaleElementReferenceException


class FootballDataScraper:
    """
    A class for scraping football match data from WhoScored.com, 
    The class also contains functions designed to scrape data for one season, one match, one league, etc.
    """
    def __init__(self, maximize_window=False):
        """
        Initializes the WhoScoredScraper instance, 
        also defines the driver settings to be used by other functions of the class.

        :param maximize_window: Whether to maximize the browser window when scraping(default: False).
        """
        options = Options()
        
        # Basic options
        options.add_argument('--no-sandbox')
        options.add_argument('--disable-dev-shm-usage')
        options.add_argument('--disable-gpu')
        options.add_argument('--disable-extensions')
        options.add_argument('--remote-debugging-port=9222')
        
        # Add these for better automation handling
        options.add_argument('--disable-blink-features=AutomationControlled')
        options.add_argument('--disable-infobars')
        
        if not maximize_window:
            options.add_argument('--headless=new')
        
        try:
            self.driver = webdriver.Chrome(
                service=Service(),
                options=options
            )
            
            if maximize_window:
                self.driver.maximize_window()
                
        except Exception as e:
            print(f"Failed to initialize driver: {e}")
            raise

    def __del__(self):
        """
        Cleans up memory by quitting the WebDriver instance. 
        Default destructor called during garbage collection.
        """
        self.driver.quit()

    def quit_driver(self):
        """
        Cleans up memory by quitting the WebDriver instance.
        Called manually if we need to quit the driver, 
        when it is not closed by garbage collector
        """
        if self.driver:
            self.driver.quit()

    def get_competition_urls(self): 
        """
        Scrapes the popular tournaments' names and URLs from a website.

        :return: A dictionary containing competition names as keys and their URLs as values.
        """
        # Open the target website
        self.driver.get("https://1xbet.whoscored.com/")

        # First, try to handle any popup that might appear
        try:
            popup_close_button = WebDriverWait(self.driver, 5).until(
                EC.element_to_be_clickable((By.XPATH, "//button[@aria-label='Close this dialog']"))
            )
            popup_close_button.click()
            time.sleep(1)  # Small delay to ensure popup is fully closed
        except (TimeoutException, NoSuchElementException):
            # If no popup is found or can't be closed, continue
            pass
        tournaments_btn = WebDriverWait(self.driver, 10).until(
            EC.element_to_be_clickable((By.XPATH, "/html/body/div[1]/div/div/div/div[4]/div[1]/div/div/button[1]"))
        )
        tournaments_btn.click()

        # Wait for the tournament grid to be visible
        WebDriverWait(self.driver, 5).until(
            EC.presence_of_element_located((By.CLASS_NAME, "TournamentsDropdownMenu-module_dropdownTournamentsGrid__Ia99x"))
        )

        # Find all tournament buttons within the grid
        tournament_elements = self.driver.find_elements(
            By.CLASS_NAME, 
            "TournamentNavButton-module_tournamentBtn__ZGW8P"
        )
    
        # Initialize dictionary to store competition names and URLs
    # Initialize dictionary to store competition names and URLs
        competitions = {}
        
        # Extract names and URLs from each tournament button
        for element in tournament_elements:
            try:
                # Find the clickable area (a tag) within the tournament button
                link_element = element.find_element(By.CLASS_NAME, "TournamentNavButton-module_clickableArea__ZFnBl")
                href = link_element.get_attribute("href")
                name = link_element.text.strip()
                
                if href and name:
                    competitions[name] = href
            except (NoSuchElementException, StaleElementReferenceException):
                continue

        return competitions

    def translate_date(self, data):
        """
        Translates date strings to a consistent format and removes matches with invalid dates.
        
        :param data: List of dictionaries containing match data with dates.
        :return: List of dictionaries with translated dates, excluding matches with invalid dates.
        """
        # Dictionary mapping various month abbreviations to standard format
        TRANSLATE_DICT = {
            'Jan': 'Jan',
            'Feb': 'Feb',
            'Mar': 'Mar',
            'Mac': 'Mar',  # Alternative spelling
            'Apr': 'Apr',
            'May': 'May',
            'Mei': 'May',  # Alternative spelling
            'Jun': 'Jun',
            'Jul': 'Jul',
            'Aug': 'Aug',
            'Ago': 'Aug',  # Alternative spelling
            'Sep': 'Sep',
            'Oct': 'Oct',
            'Okt': 'Oct',  # Alternative spelling
            'Nov': 'Nov',
            'Dec': 'Dec',
            'Des': 'Dec'   # Alternative spelling
        }

        # Find indices of matches with invalid dates (containing '?')
        unwanted_indices = [i for i, match in enumerate(data) if '?' in match['date']]

        # Remove matches with invalid dates (in reverse order to avoid index issues)
        for i in sorted(unwanted_indices, reverse=True):
            del data[i]

        # Translate dates for remaining matches
        for match in data:
            date_parts = match['date'].split()
            if len(date_parts) >= 3:  # Ensure we have all date components
                month_abbr = date_parts[0]
                if month_abbr in TRANSLATE_DICT:
                    match['date'] = ' '.join([TRANSLATE_DICT[month_abbr], date_parts[1], date_parts[2]])

        return data

    def sort_match_urls(self, data):
        """
        Sort a list of match URLs based on their dates.

        :param data: List of dictionaries containing match data with 'date' field in format 'Day, Mon DD YYYY'.
        :return: Sorted list of match URLs ordered by date.
        """
        # Sort the data using datetime.strptime to properly compare dates
        sorted_data = sorted(
            data, 
            key=lambda x: datetime.strptime(x['date'], '%A, %b %d %Y')
        )
        
        return sorted_data

    def get_match_urls(self, competitions, competition, season):
        """
        Get a list of match URLs for a specific competition and season.

        :param competition_url: URL of the competition's page.
        :param competition: Name of the competition.
        :param season: Season to fetch match URLs for.
        :return: List of match URLs.
        :raises ValueError: If the specified season is not found.
        """
        # Navigate to competition URL
        self.driver.get(competitions[competition])
        time.sleep(5)
        
        # Find and parse available seasons
        seasons = self.driver.find_element(By.XPATH, '//*[@id="seasons"]').get_attribute('innerHTML').split('\n')
        seasons = [s for s in seasons if s]  # Remove empty strings
        
        # Find and click the correct season
        for i in range(1, len(seasons) + 1):
            if self.driver.find_element(By.XPATH, f'//*[@id="seasons"]/option[{i}]').text == season:
                self.driver.find_element(By.XPATH, f'//*[@id="seasons"]/option[{i}]').click()
                time.sleep(5)
                
                try:
                    # Handle competitions with multiple stages
                    stages = self.driver.find_element(By.XPATH, '//*[@id="stages"]').get_attribute('innerHTML').split('\n')
                    stages = [s for s in stages if s]
                    
                    all_urls = []
                    
                    for i in range(1, len(stages) + 1):
                        stage_name = self.driver.find_element(By.XPATH, f'//*[@id="stages"]/option[{i}]').text
                        
                        # Handle special cases for different competition types
                        if competition in ['Champions League', 'Europa League']:
                            if not ('Grp' in stage_name or 'Final Stage' in stage_name):
                                continue
                        elif competition == 'Major League Soccer':
                            if 'Grp. ' in stage_name:
                                continue
                        
                        # Click on the stage and get match data
                        self.driver.find_element(By.XPATH, f'//*[@id="stages"]/option[{i}]').click()
                        time.sleep(5)
                        
                        self.driver.execute_script("window.scrollTo(0, 400)")
                        
                        match_urls = self.get_fixture_data()
                        match_urls = self.sort_match_urls(match_urls)
                        
                        # Filter out invalid dates
                        valid_matches = [url for url in match_urls 
                                      if '?' not in url['date'] and '\n' not in url['date']]
                        
                        all_urls.extend(valid_matches)
                        
                except NoSuchElementException:
                    # Handle competitions without stages
                    all_urls = []
                    self.driver.execute_script("window.scrollTo(0, 400)")
                    
                    match_urls = self.get_fixture_data()
                    match_urls = self.sort_match_urls(match_urls)
                    
                    valid_matches = [url for url in match_urls 
                                   if '?' not in url['date'] and '\n' not in url['date']]
                    
                    all_urls.extend(valid_matches)
                
                # Remove duplicates while preserving order
                remove_dup = [dict(t) for t in {tuple(sorted(d.items())) for d in all_urls}]
                all_urls = self.sort_match_urls(remove_dup)
                
                return all_urls
        
        # If season not found, show available seasons and raise error
        season_names = [re.search(r'\>(.*?)\<', season).group(1) for season in seasons]
        raise ValueError(f'Season not found. Available seasons: {season_names}')

    def get_team_urls(self, team, match_urls):
        """
        Get a list of match URLs for a specific team from a list of match URLs.

        :param team: Name of the team.
        :param match_urls: List of match URLs.
        :return: List of match URLs involving the specified team.
        """
        pass

    def get_fixture_data(self):
        """
        Extract match data from the current page.

        :return: List of dictionaries containing match data with format:
            {
                'date': 'Day, Mon DD YYYY',
                'home': 'Home Team Name',
                'away': 'Away Team Name',
                'score': 'Home:Away',
                'url': 'match/url/path'
            }
        """
        matches_ls = []
        while True:
            # Store initial page source to detect when we've reached the earliest matches
            initial = self.driver.page_source
            
            # Find all match date accordions
            all_fixtures = self.driver.find_elements(
                By.CLASS_NAME, 
                'Accordion-module_accordion__UuHD0'
            )
            
            for dates in all_fixtures:
                # Get all matches for this date
                fixtures = dates.find_elements(
                    By.CLASS_NAME, 
                    'Match-module_row__zwBOn'
                )
                # Get the date header
                date_row = dates.find_element(
                    By.CLASS_NAME, 
                    'Accordion-module_header__HqzWD'
                )
                
                for row in fixtures:
                    url = row.find_element(By.TAG_NAME, 'a')
                    # Only process completed matches (those with 'Live' in URL)
                    if 'Live' in url.get_attribute('href'):
                        match_dict = {}
                        # Get team names container
                        teams_tag = row.find_element(
                            By.CLASS_NAME, 
                            "Match-module_teams__sGVeq"
                        )
                        # Find match link containing score
                        link_tag = row.find_element(By.TAG_NAME, "a")
                        
                        # Build match dictionary
                        match_dict['date'] = date_row.text
                        match_dict['home'] = teams_tag.find_elements(By.TAG_NAME, 'a')[0].text
                        match_dict['away'] = teams_tag.find_elements(By.TAG_NAME, 'a')[1].text
                        match_dict['score'] = ':'.join(
                            [span.text for span in link_tag.find_elements(By.TAG_NAME, 'span')]
                        )
                        match_dict['url'] = link_tag.get_attribute('href')
                        matches_ls.append(match_dict)
            
            # Click previous button to load older matches
            prev_btn = self.driver.find_element(
                By.ID, 
                'dayChangeBtn-prev'
            )
            prev_btn.click()
            time.sleep(1)  # Wait for page to update
            
            # Check if we've reached the earliest matches
            final = self.driver.page_source
            if initial == final:
                break

        return matches_ls

    def get_match_data(self, match_url):
        """
        Retrieve match data from a given match URL.

        :param match_url: URL of the match.
        :return: Dictionary containing match data.
        """
        pass

    def get_matches_data(self, match_urls):
        """
        Retrieve match data for a list of match URLs.

        :param match_urls: List of dictionaries containing match URLs.
        :return: List of dictionaries containing match data for each match URL.
        """
        pass

    def create_matches_df(self, data):
        """
        Create a Pandas DataFrame from match data.

        :param data: Dictionary or list of dictionaries containing match data.
        :return: Pandas DataFrame with selected columns from match data.
        """
        pass

    def create_events_df(self, match_data):
        """
        Create an events DataFrame from match data.

        :param match_data: Dictionary containing match data.
        :return: Pandas DataFrame containing events data.
        """
        pass

    def get_events_df(self, match_url):
        """
        Retrieve match data and events DataFrame for a given match URL.

        :param match_url: URL of the match.
        :return: Tuple containing match data dictionary and events DataFrame.
        """
        pass

    def get_season_data(self, competition, season, team=None):
        """
        Retrieve match data for a specific competition and season.

        :param competition: Name of the competition.
        :param season: Season of the competition.
        :param team: (Optional) Team name. If provided, match data will be filtered for this team.
        :return: List of dictionaries containing match data for the specified competition and season.
        """
        pass

    def get_season_events(self, competition, season, team=None):
        """
        Retrieve season events data for a specific competition and season.

        :param competition: Name of the competition.
        :param season: Season of the competition.
        :param team: (Optional) Team name. If provided, events will be filtered for this team.
        :return: Pandas DataFrame containing season events data.
        """
        pass
    
if __name__ == "__main__":
    scraper = WhoScoredScraper(maximize_window=True)
    print(scraper.get_competition_urls())
