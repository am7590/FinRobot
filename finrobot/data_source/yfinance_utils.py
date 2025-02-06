import yfinance as yf
import pandas as pd
from typing import Annotated, Callable, Any, Optional, Tuple, Dict
from pandas import DataFrame
from functools import wraps
from datetime import datetime
from ..utils import save_output, SavePathType

class YFinanceUtils:
    @staticmethod
    def get_stock_data(
        ticker_symbol: Annotated[str, "ticker symbol"],
        start_date: Annotated[str, "start date in yyyy-mm-dd format"],
        end_date: Annotated[str, "end date in yyyy-mm-dd format"],
    ) -> Optional[pd.DataFrame]:
        """Get historical stock data for a given ticker symbol and date range"""
        try:
            # Get data directly from yfinance with auto adjustments
            ticker = yf.Ticker(ticker_symbol)
            hist = ticker.history(
                start=start_date,
                end=end_date,
                interval="1d",
                auto_adjust=True  # This handles splits and dividends automatically
            )
            
            if hist.empty:
                print(f"No historical data found for {ticker_symbol}")
                return None
                
            # Verify we have the expected columns
            required_columns = ['Open', 'High', 'Low', 'Close', 'Volume']
            if not all(col in hist.columns for col in required_columns):
                print(f"Missing required columns in data for {ticker_symbol}")
                return None
                
            return hist
        except Exception as e:
            print(f"Error fetching stock data: {str(e)}")
            return None

    @staticmethod
    def get_stock_info(ticker_symbol: Annotated[str, "ticker symbol"]) -> Optional[Dict[str, Any]]:
        """Get general information about a stock"""
        try:
            ticker = yf.Ticker(ticker_symbol)
            info = ticker.info
            if not info:
                print(f"No information found for {ticker_symbol}")
                return None
            return info
        except Exception as e:
            print(f"Error fetching stock info: {str(e)}")
            return None

    @staticmethod
    def get_company_info(
        ticker_symbol: Annotated[str, "ticker symbol"],
        save_path: Optional[str] = None,
    ) -> DataFrame:
        """Fetches and returns company information as a DataFrame."""
        try:
            ticker = yf.Ticker(ticker_symbol)
            info = ticker.info
            company_info = {
                "Company Name": info.get("shortName", "N/A"),
                "Industry": info.get("industry", "N/A"),
                "Sector": info.get("sector", "N/A"),
                "Country": info.get("country", "N/A"),
                "Website": info.get("website", "N/A"),
            }
            company_info_df = DataFrame([company_info])
            if save_path:
                company_info_df.to_csv(save_path)
                print(f"Company info for {ticker_symbol} saved to {save_path}")
            return company_info_df
        except Exception as e:
            print(f"Error fetching company info: {str(e)}")
            return DataFrame()

    @staticmethod
    def get_stock_dividends(
        ticker_symbol: Annotated[str, "ticker symbol"],
        save_path: Optional[str] = None,
    ) -> DataFrame:
        """Fetches and returns the latest dividends data as a DataFrame."""
        try:
            ticker = yf.Ticker(ticker_symbol)
            dividends = ticker.dividends
            if save_path:
                dividends.to_csv(save_path)
                print(f"Dividends for {ticker_symbol} saved to {save_path}")
            return dividends
        except Exception as e:
            print(f"Error fetching dividends: {str(e)}")
            return DataFrame()

    @staticmethod
    def get_income_stmt(ticker_symbol: Annotated[str, "ticker symbol"]) -> DataFrame:
        """Fetches and returns the latest income statement of the company as a DataFrame."""
        try:
            ticker = yf.Ticker(ticker_symbol)
            income_stmt = ticker.financials
            return income_stmt
        except Exception as e:
            print(f"Error fetching income statement: {str(e)}")
            return DataFrame()

    @staticmethod
    def get_balance_sheet(ticker_symbol: Annotated[str, "ticker symbol"]) -> DataFrame:
        """Fetches and returns the latest balance sheet of the company as a DataFrame."""
        try:
            ticker = yf.Ticker(ticker_symbol)
            balance_sheet = ticker.balance_sheet
            return balance_sheet
        except Exception as e:
            print(f"Error fetching balance sheet: {str(e)}")
            return DataFrame()

    @staticmethod
    def get_cash_flow(ticker_symbol: Annotated[str, "ticker symbol"]) -> DataFrame:
        """Fetches and returns the latest cash flow statement of the company as a DataFrame."""
        try:
            ticker = yf.Ticker(ticker_symbol)
            cash_flow = ticker.cashflow
            return cash_flow
        except Exception as e:
            print(f"Error fetching cash flow: {str(e)}")
            return DataFrame()

    @staticmethod
    def get_analyst_recommendations(
        ticker_symbol: Annotated[str, "ticker symbol"]
    ) -> Tuple[str, Optional[pd.DataFrame]]:
        """Get analyst recommendations for a stock"""
        try:
            ticker = yf.Ticker(ticker_symbol)
            recommendations = ticker.recommendations
            
            if recommendations is None or recommendations.empty:
                # Try getting from info
                info = ticker.info
                if info and 'recommendationKey' in info:
                    return info['recommendationKey'].upper(), None
                return "No Rating", None
                
            # Get the most recent recommendation
            latest_rec = recommendations.iloc[-1]
            if 'To Grade' in latest_rec:
                rating = latest_rec['To Grade']
            else:
                # Try getting from info as backup
                info = ticker.info
                if info and 'recommendationKey' in info:
                    rating = info['recommendationKey'].upper()
                else:
                    rating = "No Rating"
            
            return rating, recommendations
        except Exception as e:
            print(f"Error fetching analyst recommendations: {str(e)}")
            return "No Rating", None

if __name__ == "__main__":
    print(YFinanceUtils.get_stock_data("AAPL", "2021-01-01", "2021-12-31"))
