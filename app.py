"""Sales & Inventory Dashboard with sidebar date and category filters.

Run with:  streamlit run app.py
"""
from pathlib import Path

import pandas as pd
import plotly.express as px
import streamlit as st

# The CSV lives in the "data" folder next to this file, so the app works
# no matter which folder you start Streamlit from.
DATA_PATH = Path(__file__).parent / "data" / "sales_data.csv"

REQUIRED_COLUMNS = [
    "Order_ID",
    "Order_Date",
    "Product",
    "Category",
    "Quantity",
    "Unit_Price",
    "Total_Sales",
    "Stock_Quantity",
    "Reorder_Level",
]


def load_data(path):
    """Read the CSV and return a DataFrame. Stops the app with an error if the data is unusable."""
    if not path.exists():
        st.error(f"Data file not found: `{path}`. Please add `data/sales_data.csv` and reload.")
        st.stop()

    try:
        df = pd.read_csv(path)
    except pd.errors.EmptyDataError:
        st.error(f"The data file `{path.name}` is empty. Please add sales data and reload.")
        st.stop()

    missing = [col for col in REQUIRED_COLUMNS if col not in df.columns]
    if missing:
        st.error(f"The data file is missing these required columns: {', '.join(missing)}")
        st.stop()

    # Turn the text dates into real dates. Anything that can't be read becomes NaT (empty).
    df["Order_Date"] = pd.to_datetime(df["Order_Date"], errors="coerce")
    bad_dates = df["Order_Date"].isna().sum()
    if bad_dates > 0:
        st.error(f"{bad_dates} row(s) have an invalid Order_Date. Use the format YYYY-MM-DD.")
        st.stop()

    return df


def show_sidebar_filters(df):
    """Draw the sidebar filters and return (start_date, end_date, selected_categories)."""
    st.sidebar.header("Filters")
    st.sidebar.caption(
        "**Date range** and **Category** filter the sales metrics, charts and sales table. "
        "Inventory always uses each product's latest record and is filtered by **Category** only."
    )

    # Date range filter: defaults to the first and last order dates in the data.
    min_date = df["Order_Date"].min().date()
    max_date = df["Order_Date"].max().date()
    selected_dates = st.sidebar.date_input(
        "Order date range",
        value=(min_date, max_date),
        min_value=min_date,
        max_value=max_date,
    )

    # While the user is picking, Streamlit may return only a start date (or nothing).
    # In that case we fill in the missing end with the dataset's own range.
    if len(selected_dates) == 2:
        start_date, end_date = selected_dates
    elif len(selected_dates) == 1:
        start_date, end_date = selected_dates[0], max_date
        st.sidebar.info(f"Pick an end date to finish the range. Showing sales up to {max_date} for now.")
    else:
        start_date, end_date = min_date, max_date
        st.sidebar.info("No dates picked. Showing the full date range.")

    # Category filter: defaults to every category in the data.
    all_categories = sorted(df["Category"].unique())
    selected_categories = st.sidebar.multiselect(
        "Category",
        options=all_categories,
        default=all_categories,
    )
    if not selected_categories:
        st.sidebar.warning("No categories selected, so no sales or inventory will match.")

    return start_date, end_date, selected_categories


def filter_sales(df, start_date, end_date, categories):
    """Keep only sales inside the date range (both ends included) and in the chosen categories."""
    order_dates = df["Order_Date"].dt.date
    in_date_range = (order_dates >= start_date) & (order_dates <= end_date)
    in_categories = df["Category"].isin(categories)  # an empty list matches nothing
    return df[in_date_range & in_categories]


def calculate_sales_metrics(df):
    """Return the four headline sales numbers as a dictionary."""
    total_revenue = df["Total_Sales"].sum()
    total_orders = df["Order_ID"].nunique()  # count each order once
    units_sold = df["Quantity"].sum()

    # Average order value = revenue / orders. Guard against dividing by zero.
    if total_orders > 0:
        average_order_value = total_revenue / total_orders
    else:
        average_order_value = 0

    return {
        "total_revenue": total_revenue,
        "total_orders": total_orders,
        "units_sold": units_sold,
        "average_order_value": average_order_value,
    }


def show_sales_metrics(df):
    """Display the headline numbers in a row of metric cards."""
    metrics = calculate_sales_metrics(df)

    col1, col2, col3, col4 = st.columns(4)
    col1.metric("Total revenue", f"${metrics['total_revenue']:,.2f}")
    col2.metric("Total orders", f"{metrics['total_orders']:,}")
    col3.metric("Units sold", f"{int(metrics['units_sold']):,}")
    col4.metric("Average order value", f"${metrics['average_order_value']:,.2f}")


def show_monthly_revenue_chart(df):
    """Line chart of revenue per month, oldest month first."""
    # Group every order into its calendar month (e.g. 2026-03-14 -> March 2026).
    monthly = (
        df.groupby(df["Order_Date"].dt.to_period("M"))["Total_Sales"]
        .sum()
        .reset_index()
    )
    # Convert the month back to a date so Plotly places it on a time axis in order.
    monthly["Month"] = monthly["Order_Date"].dt.to_timestamp()
    monthly = monthly.sort_values("Month")

    fig = px.line(
        monthly,
        x="Month",
        y="Total_Sales",
        markers=True,
        title="Monthly revenue",
        labels={"Total_Sales": "Revenue ($)"},
    )
    fig.update_xaxes(dtick="M1", tickformat="%b %Y")
    fig.update_yaxes(tickprefix="$")
    st.plotly_chart(fig, use_container_width=True)


def show_revenue_by_product_chart(df):
    """Horizontal bar chart of total revenue per product, highest at the top."""
    by_product = (
        df.groupby("Product")["Total_Sales"]
        .sum()
        .reset_index()
        .sort_values("Total_Sales")  # ascending, so the biggest bar ends up at the top
    )

    fig = px.bar(
        by_product,
        x="Total_Sales",
        y="Product",
        orientation="h",
        title="Revenue by product",
        labels={"Total_Sales": "Revenue ($)", "Product": ""},
    )
    fig.update_xaxes(tickprefix="$")
    st.plotly_chart(fig, use_container_width=True)


def get_latest_inventory(df):
    """Return one row per product: its most recent recorded stock level.

    Stock_Quantity is a snapshot taken after each order, so adding the values
    up would be wrong. Instead we keep only the newest row for each product.
    """
    # Sort oldest to newest. Order_ID breaks ties when two orders share a date
    # (IDs like ORD-1001 all have the same length, so text sorting works).
    ordered = df.sort_values(["Order_Date", "Order_ID"])

    # After sorting, the last row for each product is its latest record.
    latest = ordered.groupby("Product").tail(1)

    latest = latest[["Product", "Category", "Order_Date", "Stock_Quantity", "Reorder_Level"]]
    return latest.sort_values("Product").reset_index(drop=True)


def show_inventory_table(inventory):
    """Display inventory rows with friendly column names."""
    st.dataframe(
        inventory,
        hide_index=True,
        use_container_width=True,
        column_config={
            "Order_Date": st.column_config.DateColumn("Last recorded", format="YYYY-MM-DD"),
            "Stock_Quantity": "Stock quantity",
            "Reorder_Level": "Reorder level",
        },
    )


def show_inventory_section(df, categories):
    """Show the latest stock table and any products below their reorder level.

    `df` must be the FULL dataset (not date-filtered), so each product's
    latest record is found correctly. Only the category filter is applied.
    """
    st.header("Latest recorded inventory")
    st.caption(
        "These are the most recent stock values recorded in the sample data for each product, "
        "not live stock levels. They come from the full dataset, so the sales date range does "
        "not change them; only the Category filter applies."
    )

    if not categories:
        st.info("No categories selected. Choose at least one category in the sidebar to see inventory.")
        return

    # Step 1: latest row per product from ALL data. Step 2: keep the chosen categories.
    latest = get_latest_inventory(df)
    latest = latest[latest["Category"].isin(categories)]

    show_inventory_table(latest)

    # Low stock = latest stock is below the reorder level.
    st.subheader("Low-stock products")
    low_stock = latest[latest["Stock_Quantity"] < latest["Reorder_Level"]]

    if low_stock.empty:
        st.success("No products in the selected categories are below their reorder level.")
    else:
        st.warning(f"{len(low_stock)} product(s) are below their reorder level.")
        show_inventory_table(low_stock)


def main():
    st.set_page_config(page_title="Sales & Inventory Dashboard", layout="wide")
    st.title("Sales & Inventory Dashboard")
    st.info("All data shown here is fictional sample data created for demonstration purposes.")

    df = load_data(DATA_PATH)

    # A file with headers but no rows has no dates or categories to filter on.
    if df.empty:
        st.header("Sales overview")
        show_sales_metrics(df)
        st.warning("The data file has column headers but no rows, so there is nothing to chart yet.")
        return

    start_date, end_date, categories = show_sidebar_filters(df)
    filtered_sales = filter_sales(df, start_date, end_date, categories)

    st.header("Sales overview")
    st.caption(f"Showing sales from {start_date} to {end_date} (inclusive).")
    show_sales_metrics(filtered_sales)

    # Only draw charts when there is something to draw.
    if filtered_sales.empty:
        st.info("No sales match the selected filters. Try widening the date range or adding categories.")
    else:
        left, right = st.columns(2)
        with left:
            show_monthly_revenue_chart(filtered_sales)
        with right:
            show_revenue_by_product_chart(filtered_sales)

    # Inventory uses the full dataset; it is filtered by category inside the function.
    show_inventory_section(df, categories)

    with st.expander("View filtered sales dataset"):
        if filtered_sales.empty:
            st.write("No sales match the selected filters.")
        else:
            st.dataframe(filtered_sales, hide_index=True, use_container_width=True)


if __name__ == "__main__":
    main()
