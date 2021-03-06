import pandas as pd

from src.enum import TECHIND
from src.enum import Ticker
from src.procs.OnlineVariance import OnlineVariance
from src.utils import TechInd as t

DBG = False


def proc_fill_nan(df):
    """ replaces NaN with zeros  """
    return df.fillna(0)


def proc_min_max_normalize(df, max_scale: int = 100, all_col=True, exclude_col=["Date"]):
    """
    MinMax Normalization on pandas dataframe. By defaul,t all columns will
    be processed. When specific column (say "Date" or certain category values)
    should be excluded, set the flag to False, and apass a string array of column names to exclude.


    :param df: pandas data frame
    :param max_scale: The maximum nunmber to which all values will be scaled.
    :param all_col: Set to false to esclude columns pass in the exclude_col string array
    :param exclude_col: string array (or list) with column nams to exclude.
    :return:
    """

    # replaces all NaN values with zero
    df = proc_fill_nan(df)
    if all_col:
        return ((df - df.min()) / (df.max() - df.min())) * max_scale
    else:
        # dataNorm = ((df - df.min()) / (df.max() - df.min())) * max_scale
        excluded = df[exclude_col]
        # delete all columns to exclude
        tmp = df.drop(columns=exclude_col)
        # normalize all other
        tmp = ((tmp - tmp.min()) / (tmp.max() - tmp.min())) * max_scale

        # Concatenate excluded columns and all normalized data togehter
        dataNorm = pd.concat([excluded, tmp], axis=1)

        return dataNorm


def proc_close_only(df, cont_vars):
    """
    Proc that removes the Open, High, Low, and Volume column from a standard OHLCV dataset.
    :param df: pandas dataframe
    :param cont_vars: meta-data
    :return: pandas dataframe that contains only the Close price
    """
    features = ["Open", "High", "Low", "Volume"]
    cont_vars.append("Close")
    return df.drop(columns=features)


def proc_add_datepart(df, cont_vars, cat_vars, date_col_name: str = "Date"):
    """
    Categorifies date field
    :param date_col_name:
    :param df: pandas data frame
    :param cont_vars: continous meta data
    :param cat_vars: categorial meta data
    :return: pandas data frame with date categories
    """
    # requires fast.ai install
    # add_datepart(df, date_col_name, drop=False)
    cont_vars.append("Elapsed")
    column_names = df.columns.values.tolist()
    start = column_names.index("Year")
    end = column_names.index("Is_year_end")
    for i in range(start, end):
        cat_vars.append(column_names[i])


def proc_add_next_y(df, y_column, number, cont_vars):
    """
    Adds the n-next value of the y column
    :param df:
    :param y_column:
    :param number:
    :param cont_vars:
    :return:
    """
    # https://riptutorial.com/pandas/example/24907/shifting-or-lagging-values-in-a-dataframe
    c_name = "y"
    df[c_name] = df[y_column].shift(-number)
    cont_vars.append(c_name)
    return df


def proc_add_previous_values(df, column_name, number, cont_vars):
    """ Adds n-previous values and stores each in a seperate column
        According to findings by tsfresh, the previous value can have as much
        as 88.5% significance on predicting the current value.
        https://github.com/blue-yonder/tsfresh/blob/master/notebooks/timeseries_forecasting_google_stock.ipynb
    :param df: pandas data frame
    :param column_name: source column
    :param number: number of time periods to add
    :return: Void - modifies the frame in place
    """
    for n in range(1, (number + 1)):
        df[column_name + str("-") + str(n)] = df[column_name].shift(n)
        cont_vars.append(column_name + str("-") + str(n))
    return df


def proc_add_percent_change(df, column_name, cont_vars):
    """ Calculates the percentage change for each value in the given column
    :param df: pandas data frame
    :param column_name: String - name of the column
    """
    name = "-pct"
    # simple daily percentage change
    # https://subscription.packtpub.com/book/big_data_and_business_intelligence/9781787123137/15/ch15lvl1sec126/calculating-the-simple-daily-percentage-change-in-closing-price
    # df[column_name + name] = (df[column_name] / df[column_name].shift(1) - 1) * 100
    df[column_name + name] = (df[column_name].pct_change())
    cont_vars.append(column_name + name)
    return df


def proc_add_abs_percent_change(df, column_name, cont_vars):
    """
    :param df:
    :param column_name:
    :param cont_vars:
    :return:
    """
    name = "-abs-pct"
    df[column_name + name] = abs(df[column_name] / df[column_name].shift(1) - 1) * 100
    cont_vars.append(column_name + name)
    return df


def proc_add_direction(df, column_name, cat_vars, cont_vars, noise_threshold: float = 0.07):
    """

    Adds the following direction categories, encoded as integers, in a seperate column:

    SKYFALL = -7     # percentage change falls below the bottom 10%
    STRONG_DOWN = -3 # percentage change falls below the bottom 25%
    DOWN = -1        # percentage change is negative, non-noise, but still above the bottom 25%
    ZERO = 0         # percentage change is either zero or within the noise range
    UP = 1           # percentage change is positive, above noise level, but below the 75% percentile
    STRONG_UP = 3    # percentage change is above the 75% percentile but below the top 10%
    SKY_UP = 7       # percentage change is above the top 10%

    The column containing percentage change (from the matching proc) will be added
    automatically in case it is missing.

    The noise thresholds determines the minimum percentile required to trigger a categorization.
    For example, a 7% thresholds only allows values within the 97% to pass forward while cutting
    off all other valuess. For Example, an AMZN 7 percentile thresholds cuts off
    any pct-change moves that are +/- 0.16% or less while allowing values > 0.16% or smaller than -0.16%
    You can count the number of "noises" values with the following:

        print(df["Close-direction"] == 0).sum(axis=0)

    The noise threshold percentile should be set below 0.10 to ensure that over 90% of the data get
    a direction value assigned.

    :param noise_threshold:
    :param df: pandas dataframe
    :param column_name: Name of the column from which the direction should be calculated
    :param cont_vars: continous meta data
    :param cat_vars: categorial meta data
    :return: pandas data frame with a new column, -direction
    """
    # name postfix of the new column
    name = "-direction"
    # name of the target column from which to calculate the direction move
    target = column_name + "-pct"

    # check if target column is in the data frame, if not add it
    if target not in df.columns.values.tolist():
        df = proc_add_percent_change(df=df, column_name=column_name, cont_vars=cont_vars)

    # percentile values of given column
    # https://stackoverflow.com/questions/39581893/pandas-find-percentile-stats-of-a-given-column
    # 10 th percentile = 10% of a values fall below this one
    lowest_ten_quantile = df[target].quantile(0.10)
    # 25 th percentile = 25% of a values fall below this one
    bottom_quantile = df[target].quantile(0.25)
    # 75 th percentile = 75% of a values fall below this one
    top_quantile = df[target].quantile(0.75)
    # 85 th percentile = 75% of a values fall below this one
    top_fifteen_quantile = df[target].quantile(0.85)
    # 95 th percentile = Top 10% of a values
    top_five_quantile = df[target].quantile(0.95)

    # Direction categories, encoded as integers
    SKYFALL = -7
    STRONG_DOWN = -3
    DOWN = -1
    ZERO = 0
    UP = 1
    MORE_UP = 3
    STRONG_UP = 5
    SKY_UP = 7

    # min & max threshold to exclude noise
    min_positive_pct = df[target].loc[df[target] > 0].quantile(noise_threshold)
    min_negative_pct = df[target].loc[df[target] < 0].quantile(1 - noise_threshold)

    # SKYFALL = percentage change falls below the bottom 10%
    df.loc[(df[target] < lowest_ten_quantile), column_name + name] = SKYFALL
    # STRONG_DOWN = percentage change falls below the bottom 25% but stays above the lowest 10%
    df.loc[(df[target] < bottom_quantile) & (df[target] > lowest_ten_quantile), column_name + name] = STRONG_DOWN
    # DOWN = percentage change is negative but still above the bottom 25%
    df.loc[(df[target] < min_negative_pct) & (df[target] > bottom_quantile), column_name + name] = DOWN
    #
    # ZERO, if value is either zero or within noise level
    df.loc[(df[target] > min_negative_pct) & (df[target] < min_positive_pct), column_name + name] = ZERO
    #
    # UP = percentage change is positive, above the noise threshold, but below the 75% percentile
    df.loc[(df[target] > min_positive_pct) & (df[target] < top_quantile), column_name + name] = UP
    # MORE_UP = percentage change is above the 75% percentile but below the top 15%
    df.loc[(df[target] > top_quantile) & (df[target] < top_fifteen_quantile), column_name + name] = MORE_UP
    # MORE_UP = percentage change is above the 85% percentile but below the top 5%
    df.loc[(df[target] > top_fifteen_quantile) & (df[target] < top_five_quantile), column_name + name] = STRONG_UP
    # SKY_UP = percentage change is above the top 5%
    df.loc[(df[target] > top_five_quantile), column_name + name] = SKY_UP

    # add meta data
    cat_vars.append(column_name + name)

    return df


def proc_add_volatility(df, column_name, cont_vars, nr_days=255):
    """
    Computes daily volatility for the given column using the Welford's method

    :param df: pandas data frame
    :param column_name:
    :param cont_vars: meta data
    :param nr_days: number of days to include in rolling calculatin. Defauls 1 year (255 days)
    :return: pandas data frame
    """

    # name postfix of the new column
    name = column_name + "-volatility"

    # Compute Volatility using the Welford's method
    ov = OnlineVariance()
    for n in range(nr_days):
        ov.include(df[column_name].shift(n))
    df[name] = ov.std

    cont_vars.append(name)

    return df


def proc_add_adx(df, cont_vars, stock: Ticker, change: bool = False):
    """
     Returns the average directional movement index (ADX) values for the given stock.

    :param df: pandas daframe
    :param cont_vars: meta data
    :param stock: stock ticker
    :param change: bool - when set to true, the percentage change will be added. False by default
    :return:
    """

    adx_data = t.get_cached_tech_indicator(indicator=TECHIND.TECHIND.ADX, stock=stock)
    adx_data = __rename_column(adx_data, "date", 'Date')
    convert_date(adx_data, "Date")
    # update meta data
    cont_vars.append("ADX")
    # Merge
    df_merge = pd.merge(df, adx_data, on="Date")

    if change:
        col_name = "ADX_CHANGE"
        df_merge[col_name] = df_merge["ADX"].pct_change()
        cont_vars.append(col_name)
    # replaces NaN with 0
    df_merge.fillna(0)
    return df_merge


def proc_add_obv(df, cont_vars, stock: Ticker, change: bool = False):
    """

    Adds the on balance volume (OBV) to the given data frame.

    Details: "On-Balance Volume: The Way To Smart Money"
    https://www.investopedia.com/articles/technical/100801.asp

    When change=True, then the percentage change relative to the previous value
    is added in a seperate column OBV_CHANGE

    :param df: pandas daframe
    :param cont_vars: meta data
    :param stock: stock ticker
    :param change: bool - when set to true, the percentage change will be added. False by default
    :return:
    """

    obv_data = t.get_cached_tech_indicator(indicator=TECHIND.TECHIND.OBV, stock=stock)
    obv_data = __rename_column(obv_data, "date", 'Date')
    convert_date(obv_data, "Date")
    # update meta data
    cont_vars.append("OBV")
    # Merge
    df_merge = pd.merge(df, obv_data, on="Date")

    if change:
        col_name = "OBV_CHANGE"
        df_merge[col_name] = df_merge["OBV"].pct_change()
        cont_vars.append(col_name)
    # replaces NaN with 0
    df_merge.fillna(0)
    return df_merge


def proc_add_mom(df, stock: Ticker, cont_vars, change: bool = False):
    """
    Adds momentum to the given pandas frame.
    When change = True, the percentge change in momentum will be added too

    :param df: pandas data frame
    :param cont_vars: mete data
    :param stock: stock ticker
    :param change: bool - adds percentage change. False by default
    :return: pandas data frame  with momentum data, merged over Date
    """
    mom_data = t.get_cached_tech_indicator(indicator=TECHIND.TECHIND.MOM, stock=stock)
    mom_data = __rename_column(mom_data, "date", 'Date')
    convert_date(mom_data, "Date")

    # Merge
    df_merge = pd.merge(df, mom_data, on="Date")

    # update meta data
    cont_vars.append("MOM")

    if change:
        col_name = "MOM-pct"
        df_merge[col_name] = df_merge["MOM"].pct_change()
        cont_vars.append(col_name)

    df_merge.fillna(0)  # replaces NaN with 0
    return df_merge


def proc_add_rsi(df, cont_vars, stock: Ticker, change: bool = False):
    rsi_data = t.get_cached_tech_indicator(indicator=TECHIND.TECHIND.RSI, stock=stock)
    rsi_data = __rename_column(rsi_data, "date", 'Date')
    convert_date(rsi_data, "Date")

    # update meta data
    cont_vars.append("RSI")
    # Merge
    df_merge = pd.merge(df, rsi_data, on="Date")

    if change:
        col_name = "RSI_CHANGE"
        df_merge[col_name] = df_merge["RSI"].pct_change()
        cont_vars.append(col_name)
        # replaces NaN with 0
    df_merge.fillna(0)
    return df_merge


def proc_add_ohlc_avg(df, cont_vars, add_diff: bool = False, diff_col: str = "Close",
                      add_ohlc_diff: bool = False):
    """
    Adds the average of the open, high, low, and close price to the dataframe.

    Adds distance to either a given diff_col(umn) or the distance to all four ohlc prices.

    :param df: pandas data frame
    :param cont_vars: continous mete data
    :param add_diff: bool - adds difference between ohlc_avg and a specified column
    :param diff_col: specifies column for difference calculation
    :param add_ohlc_diff: adds difference to all four ohlc prices
    :return: pandas data frame
    """
    col_name = "ohlc_avg"
    df[col_name] = ((df["Open"] + df["High"] + df["Low"] + df["Close"]) / 4)
    # update meta-data 
    cont_vars.append(col_name)

    if add_diff:

        df[diff_col + "_" + col_name + "_Diff"] = df[diff_col] - df[col_name]
        cont_vars.append(diff_col + "_" + col_name + "_Diff")
        return df

    elif add_ohlc_diff:
        ohcl = ["Open", "High", "Low", "Close"]
        for c_name in ohcl:
            # Calculate distance between specified price column and the moving average
            df[c_name + "_" + col_name + "_Diff"] = df[c_name] - df[col_name]
            # update meta data
            cont_vars.append(c_name + "_" + col_name + "_Diff")
        return df

    else:
        return df


def proc_add_bband(df, cont_vars, stock: Ticker,
                   merge_on: str = "Date",
                   add_diff_to_bb: bool = False,
                   diff_col: str = "Close",
                   add_ohlc_diff: bool = False):
    """
    Adds Bollinger Band to the dataframe for the given stock & update meta-data accordingly.
    Add the following columns:

     * 'Real Upper Band',
     * 'Real Middle Band',
     * 'Real Lower Band'

    If add_diff_to_bb is set to true, three more columns will be added. Suppose the diff_col is "Close",
    then the additional columns would be:

    * 'Close_BB_UP_Diff',
    * 'Close_BB_MID_Diff',
    * 'Close_BB_LOW_Diff'


    :param add_ohlc_diff:
    :param df: pandas dataframe
    :param stock: stock ticker
    :param cont_vars: continous mete data
    :param merge_on: shared key over which to join the BB & df table. "Date" by default.
    :param add_diff_to_bb: If true, adds the difference between the diff_column and each of the three bands
    :param diff_col: column to calculate difference to BB
    :return: data-frame that contains all previous data and the three columns of the bollinger band
    """
    bb_data = t.get_cached_tech_indicator(indicator=TECHIND.TECHIND.BBANDS, stock=stock)
    bb_data = __rename_column(bb_data, "Real Upper Band", 'BB_UP')
    bb_data = __rename_column(bb_data, "Real Middle Band", 'BB_MID')
    bb_data = __rename_column(bb_data, "Real Lower Band", 'BB_LOW')
    bb_data = __rename_column(bb_data, "date", 'Date')
    # Date needs to be converted to datetime for the table merge below.
    convert_date(bb_data, "Date")

    # update meta-data
    cont_vars = __update_meta_data(cont_vars, bb_data.columns.values.tolist())

    if DBG:
        print("Merging data with BB")
        # inner join merge over Date
        merged = pd.merge(df, bb_data, on="Date")
        print("Merged")
        print()
        print("Date len: " + str(len(df)))
        print("BB len: " + str(len(bb_data)))
        print("Merged len: " + str(len(merged)))
        print(merged.info())
        print(merged.head(3))
        print()
        print(merged.tail(3))

    if (add_diff_to_bb):
        # Merge
        df_merge = pd.merge(df, bb_data, on=merge_on)
        # Calculate distance between specified price column each of the three BB bands.
        df_merge['Close_BB_UP_Diff'] = df_merge[diff_col] - df_merge['BB_UP']
        cont_vars.append('Close_BB_UP_Diff')
        df_merge['Close_BB_MID_Diff'] = df_merge[diff_col] - df_merge['BB_MID']
        cont_vars.append('Close_BB_MID_Diff')
        df_merge['Close_BB_LOW_Diff'] = df_merge[diff_col] - df_merge['BB_LOW']
        cont_vars.append('Close_BB_LOW_Diff')
        return df_merge

    elif (add_ohlc_diff):
        # Merge
        df_merge = pd.merge(df, bb_data, on=merge_on)
        ohcl = ["Open", "High", "Low", "Close"]
        # get all Bollinger Band column names
        band_columns = bb_data.columns.values.tolist()
        band_columns.remove("Date")

        for b_name in band_columns:
            col_name = b_name
            for c_name in ohcl:
                # Calculate distance between specified price column and the moving average
                df_merge[c_name + "_" + col_name + "_Diff"] = df_merge[c_name] - df_merge[col_name]
                # update meta data
                cont_vars.append(c_name + "_" + col_name + "_Diff")

        return df_merge

    else:
        return pd.merge(df, bb_data, on=merge_on)


def proc_add_macd(df, cont_vars, stock: Ticker):
    """

    Proc returns the moving average convergence / divergence (MACD) values for the given stock.

    Also adds the difference between MACD and signal as well as percentage change for each value.

    :param df: pandas daframe
    :param cont_vars: meta data
    :param stock: stock ticker
    :return:
    """
    macd_data = t.get_cached_tech_indicator(indicator=TECHIND.TECHIND.MACD, stock=stock)
    macd_data = __rename_column(macd_data, "date", 'Date')
    convert_date(macd_data, "Date")

    macd = "MACD"
    macd_sign = "MACD_Signal"
    macd_hist = "MACD_Hist"

    # update meta data
    cont_vars.append(macd)
    cont_vars.append(macd_sign)
    cont_vars.append(macd_hist)

    # Merge
    df_merge = pd.merge(df, macd_data, on="Date")
    # captures convergence / divergence between MACD & Signal
    col_name = "MACD_SIGN_DIFF"
    df_merge[col_name] = df_merge[macd] - df_merge[macd_sign]

    cont_vars.append(col_name)
    # captures the percentage change ...
    macd_columns = macd_data.columns.values.tolist()
    macd_columns.remove("Date")
    for col in macd_columns:
        c_name = col + "_Change"
        df_merge[c_name] = df_merge[col].pct_change()
        cont_vars.append(c_name)

    return df_merge


def proc_add_wma5_wma_20_diff(df, cont_vars, stock: Ticker, add_diff: bool = False, add_ohlc_diff: bool = False):
    """

    :param df:
    :param cont_vars:
    :param stock:
    :param add_diff:
    :param add_ohlc_diff:
    :return:
    """
    wma5: str = "WMA_5"
    wma20: str = "WMA_20"
    res_name: str = "WMA_5_EMA_20_Diff"
    columns = df.columns.values.tolist()

    if wma5 not in columns:
        df = proc_add_wma5(df=df, cont_vars=cont_vars, stock=stock, add_diff=add_diff, add_ohlc_diff=add_ohlc_diff)

    if wma20 not in columns:
        df = proc_add_wma20(df=df, cont_vars=cont_vars, stock=stock, add_diff=add_diff, add_ohlc_diff=add_ohlc_diff)

    # calculate difference between WMA 20 and 60
    df[res_name] = df[wma5] - df[wma20]
    # update meta data
    cont_vars.append(res_name)

    return df


def proc_add_wma20_wma_60_diff(df, cont_vars, stock: Ticker, add_diff: bool = False, add_ohlc_diff: bool = False):
    """

    :param add_ohlc_diff:
    :param add_diff:
    :param df:
    :param cont_vars:
    :param stock:
    :return:
    """

    wma20: str = "WMA_20"
    wma60: str = "WMA_60"
    res_name: str = "WMA_20_EMA_60_Diff"
    columns = df.columns.values.tolist()

    if wma20 not in columns:
        df = proc_add_wma20(df=df, cont_vars=cont_vars, stock=stock, add_diff=add_diff, add_ohlc_diff=add_ohlc_diff)

    if wma60 not in columns:
        df = proc_add_wma60(df=df, cont_vars=cont_vars, stock=stock, add_diff=add_diff, add_ohlc_diff=add_ohlc_diff)

    # calculate difference between WMA 20 and 60
    df[res_name] = df[wma20] - df[wma60]
    # update meta data
    cont_vars.append(res_name)

    return df


def proc_add_wma60(df, cont_vars, stock: Ticker, add_diff: bool = False, diff_col: str = "Close",
                   add_ohlc_diff: bool = False):
    """
    Returns dataframe with the 60 day weighted moving average

    :param add_ohlc_diff:
    :param df: pandas data frame
    :param cont_vars: mete data
    :param stock: stock
    :param add_diff:
    :param diff_col:
    :return:
    """
    return proc_add_mov_avg(df=df, cont_vars=cont_vars, stock=stock,
                            mov_avg='wma', time_period=60, add_diff=add_diff, diff_col=diff_col,
                            add_ohlc_diff=add_ohlc_diff)


def proc_add_wma5(df, cont_vars, stock: Ticker, add_diff: bool = False, diff_col: str = "Close",
                  add_ohlc_diff: bool = False):
    """
    Returns dataframe with the 5 day weighted moving average

    :param add_ohlc_diff:
    :param df: pandas data frame
    :param cont_vars: mete data
    :param stock: stock
    :param add_diff:
    :param diff_col:
    :return:
    """
    return proc_add_mov_avg(df=df, cont_vars=cont_vars, stock=stock,
                            mov_avg='wma', time_period=5, add_diff=add_diff, diff_col=diff_col,
                            add_ohlc_diff=add_ohlc_diff)


def proc_add_wma20(df, cont_vars, stock: Ticker, add_diff: bool = False, diff_col: str = "Close",
                   add_ohlc_diff: bool = False):
    """
    Returns dataframe with the 20 day weighted moving average

    :param add_ohlc_diff:
    :param df: pandas data frame
    :param cont_vars: mete data
    :param stock: stock
    :param add_diff:
    :param diff_col:
    :return:
    """
    return proc_add_mov_avg(df=df, cont_vars=cont_vars, stock=stock,
                            mov_avg='wma', time_period=20, add_diff=add_diff, diff_col=diff_col,
                            add_ohlc_diff=add_ohlc_diff)


def proc_add_ema10_ema_30_diff(df, cont_vars, stock: Ticker, add_diff: bool = False, add_ohlc_diff: bool = False):
    """

    :param df:
    :param cont_vars:
    :param stock:
    :return:
    """
    ema10: str = "EMA_10"
    ema30: str = "EMA_30"
    res_name: str = "EMA_10_EMA_30_Diff"
    columns = df.columns.values.tolist()

    if ema10 not in columns:
        df = proc_add_ema10(df=df, cont_vars=cont_vars, stock=stock, add_diff=add_diff, add_ohlc_diff=add_ohlc_diff)

    if ema30 not in columns:
        df = proc_add_ema30(df=df, cont_vars=cont_vars, stock=stock, add_diff=add_diff, add_ohlc_diff=add_ohlc_diff)

    # calculate difference between EMA  10 and 30
    df[res_name] = df[ema10] - df[ema30]
    # update meta data
    cont_vars.append(res_name)

    return df


def proc_add_ema30(df, cont_vars, stock: Ticker, add_diff: bool = False, diff_col: str = "Close",
                   add_ohlc_diff: bool = False):
    """
    Returns dataframe with the 30 day expontial moving average

    :param add_ohlc_diff:
    :param df: pandas data frame
    :param cont_vars: mete data
    :param stock: stock
    :param add_diff:
    :param diff_col:
    :return:
    """
    return proc_add_mov_avg(df=df, cont_vars=cont_vars, stock=stock,
                            mov_avg='ema', time_period=30, add_diff=add_diff, diff_col=diff_col,
                            add_ohlc_diff=add_ohlc_diff)


def proc_add_ema10(df, cont_vars, stock: Ticker, add_diff: bool = False, diff_col: str = "Close",
                   add_ohlc_diff: bool = False):
    """
    Returns dataframe with the 10 day expontial moving average

    :param add_ohlc_diff:
    :param df: pandas data frame
    :param cont_vars: mete data
    :param stock: stock
    :param add_diff:
    :param diff_col:
    :return:
    """
    return proc_add_mov_avg(df=df, cont_vars=cont_vars, stock=stock,
                            mov_avg='ema', time_period=10, add_diff=add_diff, diff_col=diff_col,
                            add_ohlc_diff=add_ohlc_diff)


def proc_add_sma20_sma_200_diff(df, cont_vars, stock: Ticker, add_ohlc_diff: bool = False):
    """
    :param add_ohlc_diff:
    :param df:
    :param cont_vars:
    :param stock:
    :return:
    """
    sma20: str = "SMA_20"
    sma200: str = "SMA_200"
    res_name: str = "SMA_200_SMA_20_Diff"
    columns = df.columns.values.tolist()

    if sma20 not in columns:
        df = proc_add_sma20(df=df, cont_vars=cont_vars, stock=stock, add_diff=False, add_ohlc_diff=add_ohlc_diff)

    if sma200 not in columns:
        df = proc_add_sma200(df=df, cont_vars=cont_vars, stock=stock, add_diff=False, add_ohlc_diff=add_ohlc_diff)

    # calculate difference between SMA 20 and 200
    df[res_name] = df[sma20] - df[sma200]
    # update meta data
    cont_vars.append(res_name)

    return df


def proc_add_sma20(df, cont_vars, stock: Ticker, add_diff: bool = False, diff_col: str = "Close",
                   add_ohlc_diff: bool = False):
    """
    Returns dataframe with the 20 day simple moving average

    :param add_ohlc_diff:
    :param df: pandas data frame
    :param cont_vars: mete data
    :param stock: stock
    :param add_diff:
    :param diff_col:
    :return:
    """
    return proc_add_mov_avg(df=df, cont_vars=cont_vars, stock=stock, mov_avg='sma', time_period=20,
                            add_diff=add_diff, diff_col=diff_col, add_ohlc_diff=add_ohlc_diff)


def proc_add_sma200(df, cont_vars, stock: Ticker, add_diff: bool = False, diff_col: str = "Close",
                    add_ohlc_diff: bool = False):
    """

    Returns dataframe with the 200 day simple moving average

    :param add_ohlc_diff:
    :param df:
    :param cont_vars:
    :param stock:
    :param add_diff:
    :param diff_col:
    :return:
    """
    return proc_add_mov_avg(df=df, cont_vars=cont_vars, stock=stock, mov_avg='sma', time_period=200,
                            add_diff=add_diff, diff_col=diff_col, add_ohlc_diff=add_ohlc_diff)


def proc_add_mov_avg(df, cont_vars,
                     stock: Ticker,
                     mov_avg,
                     time_period: int = 20,
                     merge_on: str = "Date",
                     add_diff: bool = False,
                     diff_col: str = "Close",
                     add_ohlc_diff: bool = False):
    """
    :param df: pandas dataframe
    :param cont_vars: mete data
    :param stock: stock ticker
    :param mov_avg: moving average. Possible values: ema, sma, wma. Set to sma by default
    :param time_period: Time period for the moving average. By default 20. (i.e. 20 day SMA)
    :param merge_on: Index to merge data. Set to "Date" by default
    :param add_diff: Add a difference column that contains the difference between the specified column and the moving average. Set to False by default.
    :param diff_col: Specifies the column for calculating the difference. Set to "Close" by default
    :param add_ohlc_diff: Calculates the difference between the mov. avarage and each of the four OHLC prices.
    :return: pandas dataframe  with moving average column and diff column add_diff is set to true.
    """

    # moving average
    ma_data = __load_moving_avg(stock=stock, mov_avg=mov_avg, time_period=time_period)

    columns = ma_data.columns.values.tolist()
    # Rename to enable the inner join over "Date", which would fail w/o the rename
    ma_data = __rename_column(ma_data, "date", 'Date')
    columns = df.columns.values.tolist()

    # construct new column name with time period in it
    col_name = mov_avg.upper() + "_" + str(time_period)
    # Rename MA column
    ma_data = __rename_column(ma_data, mov_avg.upper(), col_name)
    # update meta-data
    cont_vars.append(col_name)

    # capture percent change
    chg_name = col_name + "_CHANGE"
    ma_data[chg_name] = ma_data[col_name].pct_change()
    # update meta data
    cont_vars.append(chg_name)
    # replaces NaN with 0
    ma_data.fillna(0)

    if (add_diff):
        # Merge
        df_merge = pd.merge(df, ma_data, on=merge_on)
        # Calculate distance between specified price column and the moving average
        df_merge[diff_col + "_" + col_name + "_Diff"] = df_merge[diff_col] - df_merge[col_name]
        # update meta data
        cont_vars.append(diff_col + "_" + col_name + "_Diff")

        return df_merge

    elif (add_ohlc_diff):
        # Merge
        df_merge = pd.merge(df, ma_data, on=merge_on)
        ohcl = ["Open", "High", "Low", "Close"]
        col_name = mov_avg.upper() + "_" + str(time_period)

        for c_name in ohcl:
            # Calculate distance between specified price column and the moving average
            df_merge[c_name + "_" + col_name + "_Diff"] = df_merge[c_name] - df_merge[col_name]
            # update meta data
            cont_vars.append(c_name + "_" + col_name + "_Diff")

        return df_merge

    else:
        return pd.merge(df, ma_data, on=merge_on)


def split_data(df, split_ratio:float =0.80, vrb: bool = False):
    """
    Util to split a pandas dataframe in train, test, and validation data.

    :param df: pandas data frame
    :param split_ratio: ratio between train & test
    :param vrb: Verbose. False by default
    :return: train_df, test_df
    """
    assert split_ratio <= 1.00
    assert split_ratio > 0.00

    X = df
    train_size = int(len(X) * split_ratio)
    train_df, test_df = X[0:train_size], X[train_size:len(X)]

    if vrb or DBG:
        total_len = len(train_df) + len(test_df)
        print('Observations: %d' % (len(df)))
        print("Train + Test: " + str(total_len))
        print('Training data: %d' % (len(train_df)))
        print('Testing data: %d' % (len(test_df)))

    return train_df, test_df


def inspect_data(data, cont_vars, cat_vars):
    """
    Util to inspect the pandas data frame and meta data array
    :param data: data frame
    :param cont_vars: meta data array
    :param cat_vars: meta data array
    :return: void
    """
    n = 5
    print()
    print("!!INSPECT DATA FRAME!!")
    print()
    print(data.info())
    print()
    print("Cont. meta-data: " + str(cont_vars))
    print("Cat. meta-data: " + str(cat_vars))
    print()
    print(data.head(n))
    print()
    print(data.tail(n))


def rename_data(data, crypto: bool = False):
    """
    :param data:
    :return:
    """
    data = __rename_column(data, "date", 'Date')
    data = __rename_column(data, "1. open", 'Open')
    data = __rename_column(data, "2. high", 'High')
    data = __rename_column(data, "3. low", 'Low')
    data = __rename_column(data, "4. close", 'Close')
    data = __rename_column(data, "5. volume", 'Volume')
    if crypto:
        data = __rename_column(data, "6. market cap (USD)", 'Market Cap')

    return data


def convert_date(df, date_col_name: str = None):
    """
    Converts the given date column from the standard object to an instance of datetime. 
    :param df: pandas data frame 
    :param date_col_name:
    :return: 
    """
    # Passing infer_datetime_format=True can often-times speedup a parsing
    # if its not an ISO8601 format exactly, but in a regular format.
    # https://pandas.pydata.org/pandas-docs/stable/reference/api/pandas.to_datetime.html
    # data = pd.to_datetime(data[col_name],  infer_datetime_format=True)
    df[date_col_name] = pd.to_datetime(df[date_col_name], infer_datetime_format=True)

    return df


def __load_moving_avg(stock: Ticker, mov_avg: str = 'sma', time_period: int = 20):
    """
    Helper function to load similar moving averages for the given stock
    :param stock: stock ticker
    :param mov_avg: ID of moving average possible values. set to SMA by default.
    :return: pandas data frame with the moving averge for the stock
    """
    if (mov_avg == 'sma'):
        ind = TECHIND.TECHIND.SMA
    elif (mov_avg == 'ema'):
        ind = TECHIND.TECHIND.EMA
    elif (mov_avg == 'wma'):
        ind = TECHIND.TECHIND.WMA
    else:
        ind = TECHIND.TECHIND.SMA

    ma_data = t.get_cached_tech_indicator(indicator=ind, stock=stock, time_period=time_period)
    date_col_name: str = "date"
    ma_data[date_col_name] = pd.to_datetime(ma_data[date_col_name], infer_datetime_format=True)

    return ma_data


def __rename_column(df, old_name, new_name):
    """
    Renames a column  in a pandas dataframe
    :param df: pandas dataframe
    :param old_name:
    :param new_name:
    :return: data frame with renamed column
    """
    return df.rename(index=str, columns={old_name: new_name})


def __update_meta_data(var, column_names):
    if "Date" in column_names:
        column_names.remove("Date")
    else:
        for i in range(len(column_names)):
            var.append(column_names[i])

    return var
