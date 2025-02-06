import os
import requests
import numpy as np
import pandas as pd
from datetime import datetime, timedelta
from ..utils import decorate_all_methods, get_next_weekday

# from finrobot.utils import decorate_all_methods, get_next_weekday
from functools import wraps
from typing import Annotated, List, Optional


def init_fmp_api(func):
    @wraps(func)
    def wrapper(*args, **kwargs):
        if os.environ.get("FMP_API_KEY") is None:
            print("Error: FMP_API_KEY environment variable not set")
            return None
        return func(*args, **kwargs)
    return wrapper


@decorate_all_methods(init_fmp_api)
class FMPUtils:

    @staticmethod
    def get_target_price(
        ticker_symbol: Annotated[str, "ticker symbol"],
        date: Annotated[str, "date in yyyy-mm-dd format"],
    ) -> Optional[float]:
        """Get target price for a stock on a specific date"""
        try:
            api_key = os.environ["FMP_API_KEY"]
            url = f"https://financialmodelingprep.com/api/v3/price-target?symbol={ticker_symbol}&apikey={api_key}"
            response = requests.get(url)
            response.raise_for_status()
            data = response.json()
            
            if not data:
                print(f"No target price data found for {ticker_symbol}")
                return None
                
            return float(data[0].get("priceTarget", 0))
        except Exception as e:
            print(f"Error fetching target price: {str(e)}")
            return None

    @staticmethod
    def get_sec_report(
        ticker_symbol: Annotated[str, "ticker symbol"],
        fyear: Annotated[
            str,
            "year of the 10-K report, should be 'yyyy' or 'latest'. Default to 'latest'",
        ] = "latest",
    ) -> str:
        """Get the url and filing date of the 10-K report for a given stock and year"""
        try:
            api_key = os.environ["FMP_API_KEY"]
            url = f"https://financialmodelingprep.com/api/v3/sec_filings/{ticker_symbol}?type=10-k&page=0&apikey={api_key}"

            # Send GET request
            filing_url = None
            filing_date = None
            response = requests.get(url)

            # Ensure request was successful
            if response.status_code == 200:
                # Parse JSON data
                data = response.json()
                if data and len(data) > 0:
                    if fyear == "latest":
                        filing_url = data[0]["finalLink"]
                        filing_date = data[0]["fillingDate"]
                    else:
                        for filing in data:
                            if filing["fillingDate"].split("-")[0] == fyear:
                                filing_url = filing["finalLink"]
                                filing_date = filing["fillingDate"]
                                break

                    if filing_url and filing_date:
                        return f"Link: {filing_url}\nFiling Date: {filing_date}"
            
            return None
        except Exception as e:
            print(f"Error fetching SEC report: {str(e)}")
            return None

    @staticmethod
    def get_historical_market_cap(
        ticker_symbol: Annotated[str, "ticker symbol"],
        date: Annotated[str, "date in yyyy-mm-dd format"],
    ) -> Optional[float]:
        """Get historical market cap for a stock on a specific date"""
        try:
            api_key = os.environ["FMP_API_KEY"]
            url = f"https://financialmodelingprep.com/api/v3/historical-market-capitalization/{ticker_symbol}?apikey={api_key}"
            response = requests.get(url)
            response.raise_for_status()
            data = response.json()
            
            if not data:
                print(f"No market cap data found for {ticker_symbol}")
                return None
                
            # Find the closest date
            target_date = datetime.strptime(date, "%Y-%m-%d")
            closest_data = min(data, key=lambda x: abs(datetime.strptime(x["date"], "%Y-%m-%d") - target_date))
            return float(closest_data.get("marketCap", 0))
        except Exception as e:
            print(f"Error fetching historical market cap: {str(e)}")
            return None

    @staticmethod
    def get_historical_bvps(
        ticker_symbol: Annotated[str, "ticker symbol"],
        date: Annotated[str, "date in yyyy-mm-dd format"],
    ) -> Optional[float]:
        """Get historical book value per share for a stock on a specific date"""
        try:
            api_key = os.environ["FMP_API_KEY"]
            # First try the key metrics endpoint
            url = f"https://financialmodelingprep.com/api/v3/key-metrics/{ticker_symbol}?period=annual&apikey={api_key}"
            response = requests.get(url)
            response.raise_for_status()
            data = response.json()
            
            if not data:
                # Try the ratios endpoint as backup
                url = f"https://financialmodelingprep.com/api/v3/ratios/{ticker_symbol}?period=annual&apikey={api_key}"
                response = requests.get(url)
                response.raise_for_status()
                data = response.json()
                
            if not data:
                print(f"No BVPS data found for {ticker_symbol}")
                return None
                
            # Find the closest date
            target_date = datetime.strptime(date, "%Y-%m-%d")
            closest_data = min(data, key=lambda x: abs(datetime.strptime(x["date"], "%Y-%m-%d") - target_date))
            
            # Try both possible field names
            bvps = closest_data.get("bookValuePerShare", closest_data.get("tangibleBookValuePerShare", 0))
            
            if bvps == 0:
                print(f"Warning: BVPS appears to be zero for {ticker_symbol}")
                
            return float(bvps)
        except Exception as e:
            print(f"Error fetching historical BVPS: {str(e)}")
            return None
        
    def get_financial_metrics(
        ticker_symbol: Annotated[str, "ticker symbol"],
        years: Annotated[int, "number of the years to search from, default to 4"] = 4
    ) -> pd.DataFrame:
        """Get the financial metrics for a given stock for the last 'years' years"""
        # Base URL setup for FMP API
        base_url = "https://financialmodelingprep.com/api/v3"
        # Create DataFrame
        df = pd.DataFrame()

        # Iterate over the last 'years' years of data
        for year_offset in range(years):
            # Construct URL for income statement and ratios for each year
            income_statement_url = f"{base_url}/income-statement/{ticker_symbol}?limit={years}&apikey={fmp_api_key}"
            ratios_url = (
                f"{base_url}/ratios/{ticker_symbol}?limit={years}&apikey={fmp_api_key}"
            )
            key_metrics_url = f"{base_url}/key-metrics/{ticker_symbol}?limit={years}&apikey={fmp_api_key}"

            # Requesting data from the API
            income_data = requests.get(income_statement_url).json()
            key_metrics_data = requests.get(key_metrics_url).json()
            ratios_data = requests.get(ratios_url).json()

            # Extracting needed metrics for each year
            if income_data and key_metrics_data and ratios_data:
                metrics = {
                    "Revenue": round(income_data[year_offset]["revenue"] / 1e6),
                    "Revenue Growth": "{}%".format(round(((income_data[year_offset]["revenue"] - income_data[year_offset - 1]["revenue"]) / income_data[year_offset - 1]["revenue"])*100,1)),
                    "Gross Revenue": round(income_data[year_offset]["grossProfit"] / 1e6),
                    "Gross Margin": round((income_data[year_offset]["grossProfit"] / income_data[year_offset]["revenue"]),2),
                    "EBITDA": round(income_data[year_offset]["ebitda"] / 1e6),
                    "EBITDA Margin": round((income_data[year_offset]["ebitdaratio"]),2),
                    "FCF": round(key_metrics_data[year_offset]["enterpriseValue"] / key_metrics_data[year_offset]["evToOperatingCashFlow"] / 1e6),
                    "FCF Conversion": round(((key_metrics_data[year_offset]["enterpriseValue"] / key_metrics_data[year_offset]["evToOperatingCashFlow"]) / income_data[year_offset]["netIncome"]),2),
                    "ROIC":"{}%".format(round((key_metrics_data[year_offset]["roic"])*100,1)),
                    "EV/EBITDA": round((key_metrics_data[year_offset][
                        "enterpriseValueOverEBITDA"
                    ]),2),
                    "PE Ratio": round(ratios_data[year_offset]["priceEarningsRatio"],2),
                    "PB Ratio": round(key_metrics_data[year_offset]["pbRatio"],2),
                }
                # Append the year and metrics to the DataFrame
                # Extracting the year from the date
                year = income_data[year_offset]["date"][:4]
                df[year] = pd.Series(metrics)

        df = df.sort_index(axis=1)

        return df

    def get_competitor_financial_metrics(
        ticker_symbol: Annotated[str, "ticker symbol"], 
        competitors: Annotated[List[str], "list of competitor ticker symbols"],  
        years: Annotated[int, "number of the years to search from, default to 4"] = 4
    ) -> dict:
        """Get financial metrics for the company and its competitors."""
        base_url = "https://financialmodelingprep.com/api/v3"
        all_data = {}

        symbols = [ticker_symbol] + competitors  # Combine company and competitors into one list
    
        for symbol in symbols:
            income_statement_url = f"{base_url}/income-statement/{symbol}?limit={years}&apikey={fmp_api_key}"
            ratios_url = f"{base_url}/ratios/{symbol}?limit={years}&apikey={fmp_api_key}"
            key_metrics_url = f"{base_url}/key-metrics/{symbol}?limit={years}&apikey={fmp_api_key}"

            income_data = requests.get(income_statement_url).json()
            ratios_data = requests.get(ratios_url).json()
            key_metrics_data = requests.get(key_metrics_url).json()

            metrics = {}

            if income_data and ratios_data and key_metrics_data:
                for year_offset in range(years):
                    metrics[year_offset] = {
                        "Revenue": round(income_data[year_offset]["revenue"] / 1e6),
                        "Revenue Growth": (
                            "{}%".format(round(((income_data[year_offset]["revenue"] - income_data[year_offset - 1]["revenue"]) / income_data[year_offset - 1]["revenue"])*100,1))
                            if year_offset > 0 and income_data[year_offset - 1]["revenue"] != 0 
                            else "N/A"
                        ),
                        "Gross Margin": round((income_data[year_offset]["grossProfit"] / income_data[year_offset]["revenue"]),2) if income_data[year_offset]["revenue"] != 0 else 0,
                        "EBITDA Margin": round((income_data[year_offset]["ebitdaratio"]),2),
                        "FCF Conversion": (
                            round((key_metrics_data[year_offset]["enterpriseValue"] / key_metrics_data[year_offset]["evToOperatingCashFlow"] / income_data[year_offset]["netIncome"]),2)
                            if (key_metrics_data[year_offset]["evToOperatingCashFlow"] != 0 and income_data[year_offset]["netIncome"] != 0)
                            else "N/A"
                        ),
                        "ROIC": "{}%".format(round((key_metrics_data[year_offset]["roic"])*100,1)) if key_metrics_data[year_offset]["roic"] is not None else "N/A",
                        "EV/EBITDA": round((key_metrics_data[year_offset]["enterpriseValueOverEBITDA"]),2) if key_metrics_data[year_offset]["enterpriseValueOverEBITDA"] is not None else "N/A",
                    }

            df = pd.DataFrame.from_dict(metrics, orient='index')
            df = df.sort_index(axis=1)
            all_data[symbol] = df

        return all_data



if __name__ == "__main__":
    from finrobot.utils import register_keys_from_json

    register_keys_from_json("config_api_keys")
    FMPUtils.get_sec_report("NEE", "2024")
