import json
import re
from datetime import datetime
from typing import Dict, List, Tuple, Union

import numpy as np
import pandas as pd
from bs4 import BeautifulSoup
from dateutil.relativedelta import relativedelta

import src.utils as utils

from . import COMPANIES


def get_tickers() -> None:
    for ticker, name in COMPANIES.items():
        print(ticker, "/", name)


@utils.check_company_existence
def get_isin(company: str) -> Tuple:

    if not company:
        raise Exception("Company must be defined not empty")

    url = (
        "https://www.leboursier.ma/api?method=searchStock&format=json&search=" + company
    )

    request_data = utils.get_request(url)
    # r.encoding='utf-8-sig'
    result = json.loads(request_data.content)["result"]
    len_result = len(result)

    if len_result == 0:
        raise Exception(f"Company {company} cannot be found")

    elif len_result > 1:
        names = [n["name"] for n in result]
        # TODO: add code to select the right company (in case of multiple results)
        if company in names:
            return result[0]["name"], result[0]["isin"]
        else:
            raise Exception(
                f"Found several companies with the same name {company} \n {names}"
            )
    else:
        return result[0]["name"], result[0]["isin"]


T_ed = Union[str, None]


def get_data_stock(company: str, start_date: str, end_date: T_ed) -> pd.DataFrame:

    name, isin = get_isin(company)
    url = (
        "https://www.leboursier.ma/api?method=getStockOHLC&ISIN="
        + isin
        + "&format=json"
    )

    request_data = utils.get_request(url)
    data = json.loads(request_data.content)
    data = pd.DataFrame(
        data["result"], columns=["Date", "Open", "High", "Low", "Close", "Volume"]
    )
    data.index = pd.to_datetime(
        data.Date.apply(lambda x: datetime.fromtimestamp(x / 1000.0).date())
    )
    data = data.loc[lambda x: (start_date <= x.index) & (x.index <= end_date)]
    data.set_index(
        pd.MultiIndex.from_product([[name], data.index], names=["Company", "Date"]),
        inplace=True,
    )
    data.drop(["Date"], axis=1, inplace=True)

    return data


def get_data(
    tickers: Union[str, List[str]],
    start_date: str,
    end_date: T_ed = datetime.now().strftime("%Y-%m-%d"),
) -> pd.DataFrame:

    today: datetime = datetime.now()
    six_year_from_now: datetime = today - relativedelta(years=6)

    if datetime.strptime(end_date, "%Y-%m-%d") > today:
        raise Exception(
            "end_date is greater than {today}".format(today=today.strftime("%Y-%m-%d"))
        )
    if datetime.strptime(start_date, "%Y-%m-%d") < six_year_from_now:
        raise Exception("start_date is limited to a maximum of six year")

    if isinstance(tickers, list):
        dataframes: List = [get_data_stock(t, start_date, end_date) for t in tickers]
        return pd.concat(dataframes, sort=True)
    else:
        return get_data_stock(tickers, start_date, end_date)


def get_quick_info(company: str) -> pd.DataFrame:

    pattern = re.compile(r"^(MA00000)\d+$")
    if not pattern.match(company):
        name, isin = get_isin(company)
    else:
        isin = company
    url = (
        "https://www.leboursier.ma/api?method=getStockInfo&ISIN="
        + isin
        + "&format=json"
    )

    request_data = utils.get_request(url)
    data = json.loads(request_data.content)["result"]
    data = pd.DataFrame(data.items()).T
    cols = [
        "Name",
        "Name_2",
        "ISIN",
        "Number of Shares",
        "Close",
        "Previous Close",
        "Market Cap",
        "Quotation Datetime",
        "Change",
        "Volume Change",
        "Volume in Shares",
        "Volume",
        "Open",
        "Low",
        "High",
    ]
    data.columns = cols
    data.drop(data.index[0], inplace=True)

    return data


def get_data_intraday(company: str) -> pd.DataFrame:

    _, isin = get_isin(company)
    date = (
        get_quick_info(isin)["Quotation Datetime"]
        .to_string(index=False)
        .replace("à", "")
    )
    url = (
        "https://www.leboursier.ma/api?method=getStockIntraday&ISIN="
        + isin
        + "&format=json"
    )

    request_data = utils.get_request(url)
    data = json.loads(request_data.content)["result"][0]
    data = pd.DataFrame(data)
    data.index = pd.to_datetime(
        data.labels.apply(
            lambda x: datetime.combine(
                datetime.strptime(date, "%d/%m/%Y  %H:%M").date(),
                datetime.strptime(x, "%H:%M").time(),
            )
        )
    ).rename("Datetime")
    data.drop("labels", axis=1, inplace=True)

    return data


def get_ask_bid(company: str) -> pd.DataFrame:

    _, isin = get_isin(company)
    url = f"https://www.leboursier.ma/api?method=getBidAsk&ISIN={isin}&format=json"

    request_data = utils.get_request(url)
    data = json.loads(request_data.content)["result"]["orderBook"]
    data = pd.DataFrame(data)

    return data


@utils.check_company_existence
def get_balance_sheet(company: str, period: str = "annual") -> pd.DataFrame:

    if period == "annual":
        url = (
            "https://www.marketwatch.com/investing/stock/"
            + company
            + "/financials/balance-sheet?countrycode=ma"
        )
        cols = ["Item Item", "5-year trend"]
    elif period == "quarter":
        url = (
            "https://www.marketwatch.com/investing/stock/"
            + company
            + "/financials/balance-sheet/quarter?countrycode=ma"
        )
        cols = ["Item Item", "5- qtr trend"]
    else:
        raise Exception("period should be annual or quarter")

    request_data = utils.get_request(url)
    soup = BeautifulSoup(request_data.text, "lxml")

    data = soup.find_all("table", {"class": "table table--overflow align--right"})

    tab1 = pd.read_html(str(data))[0]
    tab2 = pd.read_html(str(data))[1]
    tab1["Item Item"] = tab1["Item Item"].apply(utils.remove_duplicates)
    tab2["Item Item"] = tab2["Item Item"].apply(utils.remove_duplicates)
    tab1.set_index(
        pd.MultiIndex.from_product([["Assets"], tab1["Item Item"]], names=["", "Item"]),
        inplace=True,
    )
    tab1.drop(cols, axis=1, inplace=True)
    tab2.set_index(
        pd.MultiIndex.from_product(
            [["Liabilities & Shareholders' Equity"], tab2["Item Item"]],
            names=["", "Item"],
        ),
        inplace=True,
    )
    tab2.drop(cols, axis=1, inplace=True)
    data = pd.concat([tab1, tab2], sort=True)

    return data


@utils.check_company_existence
def get_income_statement(company: str, period: str = "annual") -> pd.DataFrame:

    if period == "annual":
        url = (
            "https://www.marketwatch.com/investing/stock/"
            + company
            + "/financials/income?countrycode=ma"
        )
        cols = ["5-year trend"]
    elif period == "quarter":
        url = (
            "https://www.marketwatch.com/investing/stock/"
            + company
            + "/financials/income/quarter?countrycode=ma"
        )
        cols = ["5- qtr trend"]
    else:
        raise Exception("period should be annual or quarter")

    request_data = utils.get_request(url)
    soup = BeautifulSoup(request_data.text, "lxml")

    data = soup.find_all("table", {"class": "table table--overflow align--right"})

    data = pd.read_html(str(data))[0]
    data["Item Item"] = data["Item Item"].apply(utils.remove_duplicates)
    data.set_index("Item Item", inplace=True)
    data.drop(cols, axis=1, inplace=True)
    data.index.rename("Item", inplace=True)

    return data


@utils.check_company_existence
def get_cash_flow(company: str, period: str = "annual") -> pd.DataFrame:

    if period == "annual":
        url = (
            "https://www.marketwatch.com/investing/stock/"
            + company
            + "/financials/cash-flow?countrycode=ma"
        )
        cols = ["Item Item", "5-year trend"]
    elif period == "quarter":
        url = (
            "https://www.marketwatch.com/investing/stock/"
            + company
            + "/financials/cash-flow/quarter?countrycode=ma"
        )
        cols = ["Item Item", "5- qtr trend"]
    else:
        raise Exception("period should be annual or quarter")

    request_data = utils.get_request(url)
    soup = BeautifulSoup(request_data.text, "lxml")

    data = soup.find_all("table", {"class": "table table--overflow align--right"})
    data = pd.read_html(str(data))
    activ = ["Operating Activities", "Investing Activities", "Financing Activities"]
    dataframes = []
    for i in range(3):
        tab = data[i]
        tab["Item Item"] = tab["Item Item"].apply(utils.remove_duplicates)
        tab.set_index(
            pd.MultiIndex.from_product(
                [[activ[i]], tab["Item Item"]], names=["", "Item"]
            ),
            inplace=True,
        )
        tab.drop(cols, axis=1, inplace=True)
        dataframes.append(tab)

    data = pd.concat(dataframes)

    return data


@utils.check_company_existence
def get_quote_table(company: str) -> pd.DataFrame:

    url = f"https://www.marketwatch.com/investing/stock/{company}?countrycode=ma"

    request_data = utils.get_request(url)
    soup = BeautifulSoup(request_data.text, "lxml")
    data = soup.find_all("li", {"class": "kv__item"})
    dataframe: Dict = {"Key Data": [], "Value": []}
    for li in data:
        dataframe["Key Data"].append(li.find("small", {"class": "label"}).contents[0])
        content = li.find("span", {"class": "primary "})
        if content is None:
            dataframe["Value"].append(np.nan)
        else:
            dataframe["Value"].append(content.contents[0].replace("د.م.", ""))
    data = pd.DataFrame(dataframe)

    return data


def get_market_status() -> str:

    url = "https://www.marketwatch.com/investing/stock/iam?countryCode=ma"

    request_data = utils.get_request(url)
    soup = BeautifulSoup(request_data.text, "lxml")
    data = soup.find_all("div", {"class": "status"})
    data = data[0].contents[0]

    return data


@utils.check_company_existence
def get_company_officers(company: str) -> pd.DataFrame:

    url = (
        "https://www.wsj.com/market-data/quotes/MA/XCAS/"
        + company
        + "/company-people"
    )

    request_data = utils.get_request(url)
    soup = BeautifulSoup(request_data.text, "lxml")
    data = soup.find_all("ul", {"class": "cr_data_collection cr_all_executives"})
    dataframe: Dict = {"Name": [], "Role": []}
    for i in data:
        div = i.find_all("div", {"class": "cr_data_field"})
        for tag in div:
            dataframe["Name"].append(tag.find("a").contents[0])
            dataframe["Role"].append(
                tag.find("span", {"class": "data_lbl"}).contents[0]
            )
    data = pd.DataFrame(dataframe)

    return data


@utils.check_company_existence
def get_company_info(company: str) -> pd.DataFrame:

    url = (
        "https://www.marketwatch.com/investing/stock/"
        + company
        + "/company-profile?countrycode=ma"
    )

    request_data = utils.get_request(url)
    soup = BeautifulSoup(request_data.text, "lxml")
    tmp = []
    tmp.append(soup.find("h4", {"class": "heading"}).contents[0])
    div_addr = soup.find_all("div", {"class": "address__line"})
    tmp.append(" ".join([x.contents[0] for x in div_addr]))
    tmp.append(
        "+"
        + soup.find("div", {"class": "phone"})
        .find("span", {"class": "text"})
        .contents[0]
    )
    div = soup.find_all("li", {"class": "kv__item w100"})
    print(div)
    tmp.append(div[0].find("span", {"class": "primary"}).contents[0])
    tmp.append(div[1].find("span", {"class": "primary"}).contents[0])
    tmp.append(soup.find("p", {"class": "description__text"}).contents[0])
    dataframe = {
        "Item": ["Name", "Address", "Phone", "Industry", "Sector", "Description"],
        "Value": tmp,
    }
    return pd.DataFrame(dataframe)
