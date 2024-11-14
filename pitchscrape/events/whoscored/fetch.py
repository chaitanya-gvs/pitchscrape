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


class WhoScoredScraper:
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
        if not maximize_window:
            options.add_argument(
                "user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/92.0.4515.107 Safari/537.36"
            )
            
        # WSL-specific options
        options.add_argument('--headless=new')  # Updated headless mode syntax
        options.add_argument('--no-sandbox')
        options.add_argument('--disable-dev-shm-usage')
        options.add_argument('--disable-gpu')
        options.add_argument('--remote-debugging-port=9222')  # Add this line
        options.add_argument('--disable-extensions')  # Add this line
        
        try:
            # Use the system's Chromium installation
            self.driver = webdriver.Chrome(
                service=Service('/usr/bin/chromedriver'),
                options=options
            )
        except Exception as e:
            print(f"Failed to initialize driver: {e}")
            raise

        if maximize_window:
            # If maximize window is set to True, make the window visible in which the driver is scraping
            self.driver.maximize_window()

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
        Translates date strings to a consistent format.

        :param data: List of dictionaries containing match data with dates.
        :return: List of dictionaries with translated dates.
        """
        pass

    def sort_match_urls(self, data):
        """
        Sort a list of match URLs based on their dates.

        :param data: List of dictionaries containing match data.
        :return: Sorted list of match URLs.
        """
        pass

    def get_match_urls(self, competition_url, competition, season):
        """
        Get a list of match URLs for a specific competition and season.

        :param competition_url: URL of the competition's page.
        :param competition: Name of the competition.
        :param season: Season to fetch match URLs for.
        :return: List of match URLs.
        """
        pass

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

        :return: List of dictionaries containing match data.
        """
        pass

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
    scraper = FootballDataScraper(maximize_window=True)
    print(scraper.get_competition_urls())
