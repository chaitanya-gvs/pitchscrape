import re
import time
import json
import numpy as np
import pandas as pd
from tqdm import tqdm, trange
from datetime import datetime
from collections import OrderedDict
import warnings
from typing import Union

from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.support.ui import WebDriverWait
from webdriver_manager.chrome import ChromeDriverManager
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import (
    NoSuchElementException,
    TimeoutException,
    StaleElementReferenceException,
    WebDriverException,
)


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
        self.BASE_URL = "https://1xbet.whoscored.com/"

        options = Options()

        # Basic options for stability
        options.add_argument("--no-sandbox")
        options.add_argument("--disable-dev-shm-usage")
        options.add_argument("--disable-gpu")
        options.add_argument("--disable-extensions")
        options.add_argument("--remote-debugging-port=9222")

        # Anti-bot detection options
        options.add_argument("--disable-blink-features=AutomationControlled")
        options.add_argument("--disable-infobars")
        options.add_experimental_option("excludeSwitches", ["enable-automation"])
        options.add_experimental_option("useAutomationExtension", False)

        # Performance options
        options.add_argument("--disable-notifications")
        options.add_argument("--disable-popup-blocking")
        options.add_argument("--disable-logging")
        options.page_load_strategy = (
            "eager"  # Load faster by not waiting for all resources
        )

        # Set a realistic user agent
        options.add_argument(
            "user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36"
        )

        if not maximize_window:
            options.add_argument("--headless=new")
            # Set a default window size for headless mode
            options.add_argument("--window-size=1920,1080")

        try:
            service = Service()
            # Set longer timeout for driver initialization
            service.start_error_message = "Chrome failed to start within 60 seconds."

            # Create driver with appropriate options
            self.driver = webdriver.Chrome(service=service, options=options)

            if maximize_window:
                self.driver.maximize_window()

            # Set default timeouts
            self.driver.set_page_load_timeout(30)
            self.driver.implicitly_wait(10)

        except Exception as e:
            print(f"Failed to initialize driver: {e}")
            raise

        # Store initial window handle
        self.main_window = self.driver.current_window_handle

    def __del__(self):
        """
        Cleans up resources by quitting the WebDriver instance.
        Default destructor called during garbage collection.
        """
        try:
            if hasattr(self, "driver"):
                self.driver.quit()
        except Exception as e:
            print(f"Error during driver cleanup: {e}")

    def cleanup_driver(self):
        """
        Explicitly cleans up WebDriver resources.
        Use this method for manual cleanup when garbage collection is unreliable.
        """
        try:
            if hasattr(self, "driver") and self.driver:
                self.driver.quit()
                self.driver = None
        except Exception as e:
            print(f"Error during manual driver cleanup: {e}")

    def fetch_competitions(self) -> dict[str, str]:
        """
        Scrapes the popular tournaments' names and URLs from WhoScored.com.

        :return: dict[str, str]: Dictionary mapping competition names to their URLs
                Example: {'Premier League': 'https://...', 'LaLiga': 'https://...'}
        """
        POPUP_TIMEOUT = 5
        DROPDOWN_TIMEOUT = 10
        GRID_TIMEOUT = 5

        # Navigate to the website
        self.driver.get(self.BASE_URL)

        # Handle potential popup dialog
        try:
            dialog_close_button = WebDriverWait(self.driver, POPUP_TIMEOUT).until(
                EC.element_to_be_clickable(
                    (By.XPATH, "//button[@aria-label='Close this dialog']")
                )
            )
            dialog_close_button.click()
            time.sleep(1)  # Ensure popup closes completely
        except (TimeoutException, NoSuchElementException):
            pass

        # Click tournaments dropdown
        competitions_dropdown = WebDriverWait(self.driver, DROPDOWN_TIMEOUT).until(
            EC.element_to_be_clickable(
                (
                    By.XPATH,
                    "/html/body/div[1]/div/div/div/div[4]/div[1]/div/div/button[1]",
                )
            )
        )
        competitions_dropdown.click()

        # Wait for competitions grid
        competition_grid_class = (
            "TournamentsDropdownMenu-module_dropdownTournamentsGrid__Ia99x"
        )
        WebDriverWait(self.driver, GRID_TIMEOUT).until(
            EC.presence_of_element_located((By.CLASS_NAME, competition_grid_class))
        )

        # Get all competition buttons
        competition_buttons = self.driver.find_elements(
            By.CLASS_NAME, "TournamentNavButton-module_tournamentBtn__ZGW8P"
        )

        # Store competition data
        competitions = {}
        processed_names = set()  # Track processed competition names

        # Extract competition information
        for competition_button in competition_buttons:
            try:
                competition_link = competition_button.find_element(
                    By.CLASS_NAME, "TournamentNavButton-module_clickableArea__ZFnBl"
                )
                competition_url = competition_link.get_attribute("href")
                competition_name = competition_link.text.strip()

                # Handle duplicate Premier League case
                if (
                    competition_name == "Premier League"
                    and competition_name in processed_names
                ):
                    competition_name = "Russian Premier League"

                # Store unique competitions
                if competition_url and competition_name not in processed_names:
                    competitions[competition_name] = competition_url
                    processed_names.add(competition_name)

            except (NoSuchElementException, StaleElementReferenceException):
                continue

        return competitions

    def standardize_date(self, match_data: list[dict]) -> list[dict]:
        """
        Standardizes date formats and filters out matches with invalid dates.

        :param match_data: List of dictionaries containing match information with dates
                         Expected format: [{'date': 'Mon DD YYYY', ...}, ...]
        :return: List of dictionaries with standardized dates, excluding invalid dates
        :raises ValueError: If match_data is empty or has invalid structure

        Example:
            Input: [{'date': 'Okt 15 2023', ...}, {'date': '? ? ?', ...}]
            Output: [{'date': 'Oct 15 2023', ...}]
        """
        if not match_data:
            raise ValueError("Empty match data provided")

        # Dictionary mapping various month abbreviations to standard format
        MONTH_MAPPINGS = {
            # English standard
            "Jan": "Jan",
            "Feb": "Feb",
            "Mar": "Mar",
            "Apr": "Apr",
            "May": "May",
            "Jun": "Jun",
            "Jul": "Jul",
            "Aug": "Aug",
            "Sep": "Sep",
            "Oct": "Oct",
            "Nov": "Nov",
            "Dec": "Dec",
            # Alternative spellings
            "Mac": "Mar",  # Malaysian
            "Mei": "May",  # Indonesian
            "Ago": "Aug",  # Spanish/Portuguese
            "Okt": "Oct",  # German/Dutch
            "Des": "Dec",  # Indonesian
        }

        # Create a new list instead of modifying the input
        valid_matches = []

        for match in match_data:
            try:
                date_string = match.get("date", "")

                # Skip matches with invalid dates
                if "?" in date_string:
                    continue

                date_components = date_string.split()

                # Validate date components
                if len(date_components) < 3:
                    print(f"Warning: Invalid date format found: {date_string}")
                    continue

                month = date_components[0]

                # Standardize month if mapping exists
                if month in MONTH_MAPPINGS:
                    standardized_date = " ".join(
                        [MONTH_MAPPINGS[month], date_components[1], date_components[2]]
                    )
                    match["date"] = standardized_date
                    valid_matches.append(match)
                else:
                    print(f"Warning: Unknown month abbreviation found: {month}")
                    continue

            except (KeyError, IndexError) as e:
                print(f"Error processing match data: {e}")
                continue

        if not valid_matches:
            print("Warning: No valid matches found after date translation")

        return valid_matches

    def sort_matches(self, match_data: list[dict]) -> list[dict]:
        """
        Sort a list of match URLs based on their dates.

        :param match_data: List of dictionaries containing match information
                         Expected format: [{'date': 'Monday, Jan 15 2024', ...}, ...]
        :return: List of dictionaries sorted by date in ascending order
        :raises ValueError: If match_data is empty or contains invalid date formats
        """
        if not match_data:
            raise ValueError("Empty match data provided")

        try:
            # First standardize the dates
            standardized_matches = self.standardize_date(match_data)
            
            # Parse standardized dates for sorting
            DATE_FORMAT = "%b %d %Y"  # Format after standardization: "Jan 15 2024"
            sorted_matches = sorted(
                standardized_matches,
                key=lambda match: datetime.strptime(match.get("date", ""), DATE_FORMAT)
            )

            if not sorted_matches:
                print("Warning: No matches found after sorting")

            return sorted_matches

        except ValueError as e:
            print(f"Error sorting matches: {e}")
            raise
        except Exception as e:
            print(f"Unexpected error during sorting: {e}")
            raise

    def fetch_matches(
        self, competition_urls: dict, competition_name: str, season: str
    ) -> list[dict]:
        """
        Get a list of match URLs for a specific competition and season.

        :param competition_urls: Dictionary mapping competition names to their URLs
        :param competition_name: Name of the competition to fetch matches for
        :param season: Season to fetch match URLs for (format: 'YYYY/YYYY')
        :return: List of dictionaries containing match information and URLs
        :raises ValueError: If the specified season is not found
        """
        TIMEOUT = 10
        PAGE_UPDATE_DELAY = 5
        SCROLL_DELAY = 2
        MAX_RETRIES = 3

        def wait_and_find_element(by, value, timeout=TIMEOUT, retries=MAX_RETRIES):
            """Helper function to handle stale elements"""
            for attempt in range(retries):
                try:
                    element = WebDriverWait(self.driver, timeout).until(
                        EC.presence_of_element_located((by, value))
                    )
                    return element
                except (StaleElementReferenceException, TimeoutException) as e:
                    if attempt == retries - 1:  # Last attempt
                        raise e
                    time.sleep(1)

        # Navigate to competition URL
        self.driver.get(competition_urls[competition_name])
        time.sleep(PAGE_UPDATE_DELAY)

        # Find and parse available seasons
        season_dropdown = wait_and_find_element(By.XPATH, '//*[@id="seasons"]')
        available_seasons = season_dropdown.get_attribute("innerHTML").split("\n")
        available_seasons = [
            season_text for season_text in available_seasons if season_text
        ]

        # Find and select the requested season
        season_found = False
        for season_index in range(1, len(available_seasons) + 1):
            try:
                season_option = wait_and_find_element(
                    By.XPATH, f'//*[@id="seasons"]/option[{season_index}]'
                )
                if season_option.text == season:
                    season_option.click()
                    season_found = True
                    time.sleep(PAGE_UPDATE_DELAY)
                    break
            except StaleElementReferenceException:
                continue

        if not season_found:
            season_list = [
                re.search(r"\>(.*?)\<", season_text).group(1)
                for season_text in available_seasons
            ]
            raise ValueError(f"Season not found. Available seasons: {season_list}")

        try:
            # Wait for competition stages dropdown
            stages_dropdown = wait_and_find_element(By.XPATH, '//*[@id="stages"]')
            competition_stages = stages_dropdown.get_attribute("innerHTML").split("\n")
            competition_stages = [stage for stage in competition_stages if stage]

            match_url_list = []

            for stage_index in range(1, len(competition_stages) + 1):
                try:
                    stage_option = wait_and_find_element(
                        By.XPATH, f'//*[@id="stages"]/option[{stage_index}]'
                    )
                    stage_name = stage_option.text

                    # Filter unwanted stages based on competition type
                    if competition_name in ["Champions League", "Europa League"]:
                        if not ("Grp" in stage_name or "Final Stage" in stage_name):
                            continue
                    elif competition_name == "Major League Soccer":
                        if "Grp. " in stage_name:
                            continue

                    # Select stage and wait for page update
                    stage_option.click()
                    time.sleep(PAGE_UPDATE_DELAY)

                    # Scroll to load more matches
                    self.driver.execute_script("window.scrollTo(0, 400)")
                    time.sleep(SCROLL_DELAY)

                    # Get and process match URLs
                    stage_matches = self.fetch_match_overview()
                    sorted_matches = self.sort_matches(stage_matches)

                    # Filter valid matches
                    valid_stage_matches = [
                        match
                        for match in sorted_matches
                        if "?" not in match["date"] and "\n" not in match["date"]
                    ]

                    match_url_list.extend(valid_stage_matches)
                except StaleElementReferenceException:
                    continue

        except TimeoutException:
            # Handle competitions without stages
            print("No stages found, fetching matches directly")
            self.driver.execute_script("window.scrollTo(0, 400)")
            time.sleep(SCROLL_DELAY)

            all_matches = self.fetch_match_overview()
            sorted_matches = self.sort_matches(all_matches)

            match_url_list = [
                match
                for match in sorted_matches
                if "?" not in match["date"] and "\n" not in match["date"]
            ]

        # Remove duplicates while preserving order
        unique_matches = [
            dict(t) for t in {tuple(sorted(d.items())) for d in match_url_list}
        ]
        sorted_unique_matches = self.sort_matches(unique_matches)

        return sorted_unique_matches

    def filter_team_matches(self, match_urls: list[dict], team_name: str) -> list[dict]:
        """
        Get a list of match URLs for a specific team from a list of match URLs.

        :param match_urls: List of dictionaries containing match information
                         Expected format: [{'url': 'str', 'home': 'str', 'away': 'str', ...}, ...]
        :param team_name: Name of the team to filter matches for
        :return: List of match URLs involving the specified team
        :raises ValueError: If match_urls is empty or team_name is not found in any match

        Example:
            Input:
                match_urls = [
                    {'url': 'match1', 'home': 'Barcelona', 'away': 'Real Madrid'},
                    {'url': 'match2', 'home': 'Barcelona', 'away': 'Valencia'}
                ]
                team_name = 'Barcelona'
            Output:
                [
                    {'url': 'match1', 'home': 'Barcelona', 'away': 'Real Madrid'},
                    {'url': 'match2', 'home': 'Barcelona', 'away': 'Valencia'}
                ]
        """
        if not match_urls:
            raise ValueError("Empty match URLs provided")

        if not team_name:
            raise ValueError("Team name cannot be empty")

        # Create a dictionary to store unique match data involving the specified team
        team_matches = {
            match["url"]: match
            for match in match_urls
            if team_name in (match.get("home"), match.get("away"))
        }

        if not team_matches:
            raise ValueError(f"No matches found for team: {team_name}")

        # Convert dictionary values to list, preserving match order
        filtered_matches = list(team_matches.values())

        print(f"Found {len(filtered_matches)} matches for {team_name}")
        return filtered_matches

    def fetch_match_overview(self):
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
        matches_data = []
        while True:
            # Store initial page source to detect when we've reached the earliest matches
            initial_page = self.driver.page_source

            # Find all match date accordions
            date_accordions = self.driver.find_elements(
                By.CLASS_NAME, "Accordion-module_accordion__UuHD0"
            )

            for date_section in date_accordions:
                # Get all matches for this date
                match_rows = date_section.find_elements(
                    By.CLASS_NAME, "Match-module_row__zwBOn"
                )
                # Get the date header
                date_header = date_section.find_element(
                    By.CLASS_NAME, "Accordion-module_header__HqzWD"
                )

                for match_row in match_rows:
                    match_link = match_row.find_element(By.TAG_NAME, "a")
                    # Only process completed matches (those with 'Live' in URL)
                    if "Live" in match_link.get_attribute("href"):
                        match_info = {}
                        # Get team names container
                        teams_container = match_row.find_element(
                            By.CLASS_NAME, "Match-module_teams__sGVeq"
                        )
                        # Find match link containing score
                        score_link = match_row.find_element(By.TAG_NAME, "a")

                        # Build match dictionary
                        match_info["date"] = date_header.text
                        match_info["home"] = teams_container.find_elements(
                            By.TAG_NAME, "a"
                        )[0].text
                        match_info["away"] = teams_container.find_elements(
                            By.TAG_NAME, "a"
                        )[1].text
                        match_info["score"] = ":".join(
                            [
                                span.text
                                for span in score_link.find_elements(
                                    By.TAG_NAME, "span"
                                )
                            ]
                        )
                        match_info["url"] = score_link.get_attribute("href")
                        matches_data.append(match_info)

            # Click previous button to load older matches
            previous_button = self.driver.find_element(By.ID, "dayChangeBtn-prev")
            previous_button.click()
            time.sleep(1)  # Wait for page to update

            # Check if we've reached the earliest matches
            final_page = self.driver.page_source
            if initial_page == final_page:
                break

        return matches_data

    def fetch_match_data(self, match_url):
        """
        Retrieve match data from a given match URL.

        :param match_url: URL of the match.
        :return: Dictionary containing match data.
        """
        try:
            self.driver.get(match_url)
        except WebDriverException as e:
            return str(e)

        time.sleep(5)
        # Get script data from page source
        script_content = self.driver.find_element(
            By.XPATH, '//*[@id="layout-wrapper"]/script[1]'
        ).get_attribute("innerHTML")

        # Clean script content
        script_content = re.sub(r"[\n\t]*", "", script_content)
        script_content = script_content[
            script_content.index("matchId") : script_content.rindex("}")
        ]

        # This will give script content in list form
        script_content_list = list(
            filter(None, script_content.strip().split(",            "))
        )
        metadata = script_content_list.pop(1)

        # String format to JSON format
        match_data = json.loads(metadata[metadata.index("{") :])
        keys = [item[: item.index(":")].strip() for item in script_content_list]
        values = [item[item.index(":") + 1 :].strip() for item in script_content_list]
        for key, val in zip(keys, values):
            match_data[key] = json.loads(val)

        # Get other details about the match
        region = self.driver.find_element(
            By.XPATH, '//*[@id="breadcrumb-nav"]/span[1]'
        ).text
        league = self.driver.find_element(
            By.XPATH, '//*[@id="breadcrumb-nav"]/a'
        ).text.split(" - ")[0]
        season = self.driver.find_element(
            By.XPATH, '//*[@id="breadcrumb-nav"]/a'
        ).text.split(" - ")[1]

        if (
            len(
                self.driver.find_element(
                    By.XPATH, '//*[@id="breadcrumb-nav"]/a'
                ).text.split(" - ")
            )
            == 2
        ):
            competition_type = "League"
            competition_stage = ""
        elif (
            len(
                self.driver.find_element(
                    By.XPATH, '//*[@id="breadcrumb-nav"]/a'
                ).text.split(" - ")
            )
            == 3
        ):
            competition_type = "Knock Out"
            competition_stage = self.driver.find_element(
                By.XPATH, '//*[@id="breadcrumb-nav"]/a'
            ).text.split(" - ")[-1]
        else:
            print("Getting more than 3 types of information about the competition.")

        match_data["region"] = region
        match_data["league"] = league
        match_data["season"] = season
        match_data["competitionType"] = competition_type
        match_data["competitionStage"] = competition_stage

        # Sort match_data dictionary alphabetically
        match_data = OrderedDict(sorted(match_data.items()))
        match_data = dict(match_data)

        return match_data

    def fetch_matches_data(
        self, match_urls: list[dict], minimize_window: bool = True
    ) -> list[dict]:
        """
        Retrieve detailed match data for a list of match URLs.

        :param match_urls: List of dictionaries containing match information and URLs
                         Expected format: [{'url': 'str', ...}, ...]
        :param minimize_window: Whether to minimize the browser window while scraping
        :return: List of dictionaries containing detailed match data
        :raises ValueError: If match_urls is empty

        Example:
            Input: [{'url': 'match1_url'}, {'url': 'match2_url'}]
            Output: [
                {'matchId': '1234', 'home': 'Team1', 'away': 'Team2', ...},
                {'matchId': '5678', 'home': 'Team3', 'away': 'Team4', ...}
            ]
        """
        SCRAPE_DELAY = 7  # Delay between requests to avoid bot detection

        if not match_urls:
            raise ValueError("Empty match URLs provided")

        collected_matches = []
        total_matches = len(match_urls)

        def process_match(match_url: str) -> None:
            """Helper function to process a single match"""
            time.sleep(SCRAPE_DELAY)  # Anti-bot detection delay
            match_details = self.fetch_match_data(match_url)
            collected_matches.append(match_details)

        try:
            for index in trange(total_matches, desc="Fetching Match Data"):
                process_match(match_urls[index]["url"])

        except ImportError:
            print("Note: Install tqdm package for progress tracking (pip install tqdm)")

            for index in range(total_matches):
                process_match(match_urls[index]["url"])
                print(f"Processing match {index + 1}/{total_matches}")

        except Exception as e:
            print(f"Error during match data collection: {e}")
            raise

        if not collected_matches:
            print("Warning: No match data was collected")

        return collected_matches

    def extract_match_details(
        self, match_data: Union[dict, list[dict]]
    ) -> pd.DataFrame:
        """
        Create a Pandas DataFrame from match data with selected columns.

        :param match_data: Single match dictionary or list of match dictionaries
                         Must contain basic match information (matchId, teams, venue, etc.)
        :return: Pandas DataFrame indexed by matchId with standardized match information
        :raises ValueError: If input data is empty or has invalid format

        Example:
            Input: [{
                'matchId': '1234',
                'home': 'Barcelona',
                'away': 'Real Madrid',
                'attendance': 95000,
                ...
            }]
            Output: DataFrame(
                index='matchId',
                columns=['attendance', 'venueName', 'startTime', ...]
            )
        """
        # Define standard column names and their display labels
        MATCH_COLUMNS = {
            "matchId": "Match Identifier",
            "attendance": "Stadium Attendance",
            "venueName": "Stadium Name",
            "startTime": "Kickoff Time",
            "startDate": "Match Date",
            "score": "Final Score",
            "home": "Home Team",
            "away": "Away Team",
            "referee": "Match Referee",
        }

        def validate_match_data(input_data: Union[dict, list[dict]]) -> list[dict]:
            """Validate and standardize input match data"""
            if not input_data:
                raise ValueError("Empty match data provided")

            # Convert single match dictionary to list
            if isinstance(input_data, dict):
                return [input_data]
            elif isinstance(input_data, list):
                if not all(isinstance(match_entry, dict) for match_entry in input_data):
                    raise ValueError("All elements must be dictionaries")
                return input_data
            else:
                raise ValueError(
                    f"Expected dict or list of dicts, got {type(input_data).__name__}"
                )

        try:
            # Validate and standardize input
            validated_matches = validate_match_data(match_data)

            # Create DataFrame directly from validated data
            match_dataframe = pd.DataFrame(validated_matches)

            # Select and rename required columns
            match_dataframe = match_dataframe[MATCH_COLUMNS.keys()]
            match_dataframe.rename(columns=MATCH_COLUMNS, inplace=True)

            # Set index and handle missing values
            match_dataframe.set_index("Match Identifier", inplace=True)
            match_dataframe.fillna(np.nan, inplace=True)

            # Validate that we have data
            if match_dataframe.empty:
                print("Warning: Created DataFrame contains no match data")

            return match_dataframe

        except KeyError as missing_column:
            raise ValueError(f"Required match column missing: {missing_column}")
        except Exception as error:
            raise ValueError(f"Error creating match DataFrame: {error}")

    def extract_events(self, match_data):
        """
        Create an events DataFrame from match data.

        :param match_data: Dictionary containing match data.
        :return: Pandas DataFrame containing events data.
        """
        events = match_data["events"]

        for event in events:
            event.update(
                {
                    "matchId": match_data["matchId"],
                    "startDate": match_data["startDate"],
                    "startTime": match_data["startTime"],
                    "score": match_data["score"],
                    "ftScore": match_data["ftScore"],
                    "htScore": match_data["htScore"],
                    "etScore": match_data["etScore"],
                    "venueName": match_data["venueName"],
                    "maxMinute": match_data["maxMinute"],
                }
            )

        events_df = pd.DataFrame(events)

        # Clean period column
        events_df["period"] = pd.json_normalize(events_df["period"])["displayName"]

        # Clean type column
        events_df["type"] = pd.json_normalize(events_df["type"])["displayName"]

        # Clean outcomeType column
        events_df["outcomeType"] = pd.json_normalize(events_df["outcomeType"])[
            "displayName"
        ]

        # Clean cardType column
        try:
            x = events_df["cardType"].fillna({i: {} for i in events_df.index})
            events_df["cardType"] = pd.json_normalize(x)["displayName"].fillna(False)
        except KeyError:
            events_df["cardType"] = False

        eventTypeDict = match_data["matchCentreEventTypeJson"]
        events_df["satisfiedEventsTypes"] = events_df["satisfiedEventsTypes"].apply(
            lambda x: [
                list(eventTypeDict.keys())[list(eventTypeDict.values()).index(event)]
                for event in x
            ]
        )

        # Clean qualifiers column
        try:
            for i in events_df.index:
                row = events_df.loc[i, "qualifiers"].copy()
                if len(row) != 0:
                    for irow in range(len(row)):
                        row[irow]["type"] = row[irow]["type"]["displayName"]
        except TypeError:
            pass

        # Clean isShot column
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", category=FutureWarning)
            if "isShot" in events_df.columns:
                events_df["isShot"] = (
                    events_df["isShot"].replace(np.nan, False).infer_objects(copy=False)
                )
            else:
                events_df["isShot"] = False

        # Clean isGoal column
        if "isGoal" in events_df.columns:
            events_df["isGoal"] = (
                events_df["isGoal"].replace(np.nan, False).infer_objects(copy=False)
            )
        else:
            events_df["isGoal"] = False

        # Add player name column
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", category=FutureWarning)
            events_df.loc[events_df.playerId.notna(), "playerId"] = (
                events_df.loc[events_df.playerId.notna(), "playerId"]
                .astype(int)
                .astype(str)
            )
        player_name_col = events_df.loc[:, "playerId"].map(
            match_data["playerIdNameDictionary"]
        )
        events_df.insert(
            loc=events_df.columns.get_loc("playerId") + 1,
            column="playerName",
            value=player_name_col,
        )

        # Add home/away column
        h_a_col = events_df["teamId"].map(
            {match_data["home"]["teamId"]: "h", match_data["away"]["teamId"]: "a"}
        )
        events_df.insert(
            loc=events_df.columns.get_loc("teamId") + 1, column="h_a", value=h_a_col
        )

        # Adding shot body part column
        events_df["shotBodyType"] = np.nan
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", category=FutureWarning)
            for i in events_df.loc[events_df.isShot == True].index:
                for j in events_df.loc[events_df.isShot == True].qualifiers.loc[i]:
                    if j["type"] in ["RightFoot", "LeftFoot", "Head", "OtherBodyPart"]:
                        events_df.loc[i, "shotBodyType"] = j["type"]

        # Adding shot situation column
        events_df["situation"] = np.nan
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", category=FutureWarning)
            for i in events_df.loc[events_df.isShot == True].index:
                for j in events_df.loc[events_df.isShot == True].qualifiers.loc[i]:
                    if j["type"] in ["FromCorner", "SetPiece", "DirectFreekick"]:
                        events_df.loc[i, "situation"] = j["type"]
                    if j["type"] == "RegularPlay":
                        events_df.loc[i, "situation"] = "OpenPlay"

        event_types = list(match_data["matchCentreEventTypeJson"].keys())
        event_type_cols = pd.DataFrame(
            {
                event_type: pd.Series(
                    [event_type in row for row in events_df["satisfiedEventsTypes"]]
                )
                for event_type in event_types
            }
        )
        events_df = pd.concat([events_df, event_type_cols], axis=1)

        return events_df

    def fetch_match_events(self, match_url):
        """
        Retrieve match data and events DataFrame for a given match URL.

        :param match_url: URL of the match.
        :return: Tuple containing match data dictionary and events DataFrame.
        """

        try:
            match_data = self.fetch_match_data(match_url)
            # Create events DataFrame
            print(match_data)
            events_df = self.extract_events(match_data)

            return match_data, events_df

        except Exception as e:
            print(f"Error retrieving events data: {e}")
            return None, None
        # Ensure the driver is closed

    def collate_season_data(self, competition, season, team=None):
        """
        Retrieve match data for a specific competition and season.

        :param competition: Name of the competition.
        :param season: Season of the competition.
        :param team: (Optional) Team name. If provided, match data will be filtered for this team.
        :return: List of dictionaries containing match data for the specified competition and season.
        """
        try:
            # Get competition URLs
            competition_urls = self.fetch_competitions()

            # Get match URLs for the competition and season
            match_urls = self.fetch_matches(competition_urls, competition, season)

            # Filter for specific team if provided
            if team:
                match_urls = self.filter_team_matches(
                    team_name=team, match_urls=match_urls
                )

            # Get detailed match data
            matches_data = self.fetch_matches_data(match_urls[:2])

            return matches_data

        except Exception as e:
            print(f"Error retrieving season data: {e}")
            return None

    def collate_season_events(self, competition, season, team=None):
        """
        Retrieve season events data for a specific competition and season.

        :param competition: Name of the competition.
        :param season: Season of the competition.
        :param team: (Optional) Team name. If provided, events will be filtered for this team.
        :return: Pandas DataFrame containing season events data.
        """
        try:
            # Get match data for the season
            matches_data = self.collate_season_data(competition, season, team)

            if not matches_data:
                return None

            # Create events DataFrame for each match and concatenate
            all_events = []
            for match in matches_data:
                events_df = self.extract_events(match)
                all_events.append(events_df)

            # Combine all events into a single DataFrame
            if all_events:
                combined_events = pd.concat(all_events, ignore_index=True)
                return combined_events
            else:
                print("No events data found")
                return None

        except Exception as e:
            print(f"Error retrieving season events: {e}")
            return None


if __name__ == "__main__":
    scraper = WhoScoredScraper(maximize_window=True)
    # competitions = scraper.fetch_competitions()
    # match_urls = scraper.fetch_matches(competitions, 'LaLiga', '2023/2024')
    # team_urls = scraper.filter_team_matches(match_urls, "Barcelona")
    # match_data = scraper.fetch_matches_data(team_urls[0:2])
    # match_df = scraper.extract_match_details(match_data)
    # print(match_urls[0])
    # events_df = scraper.fetch_match_events(match_urls[0]['url'])
    # season_data = scraper.collate_season_data('LaLiga', '2023/2024')
    # season_events = scraper.collate_season_events("LaLiga", "2023/2024", "Barcelona")
    match_data = scraper.fetch_match_data(
        "https://www.whoscored.com/Matches/1821585/Live/Spain-LaLiga-2024-2025-Atletico-Madrid-Sevilla"
    )
    match_df = scraper.extract_match_details(match_data)
    events_df = scraper.extract_events(match_data)
    # print(match_data.keys())
    # print(season_events)
    # print(season_events)

