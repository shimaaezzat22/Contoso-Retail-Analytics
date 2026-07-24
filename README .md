# 🛒 Enterprise Retail Analytics Solution

An enterprise-scale Business Intelligence solution built using the **Microsoft Contoso Retail (32 GB)** dataset.

This project focuses on designing a scalable analytics architecture capable of handling large datasets by combining SQL Server, Python automation, and Power BI best practices.

---

# 📖 Project Overview

The Microsoft Contoso Retail dataset (~32 GB) presents a realistic enterprise BI scenario where choosing the appropriate data architecture is just as important as building the dashboard itself.

Rather than connecting Power BI directly to the source tables, this project follows a layered architecture to improve performance, maintainability, and scalability.

---

# 🏗️ Solution Architecture

```
Microsoft SQL Server
        │
        ▼
Reporting Semantic Layer (SQL Views)
        │
        ▼
Python ETL Pipeline (VS Code)
        │
        ▼
Optimized Parquet Files
        │
        ▼
Power BI Semantic Model
        │
        ▼
Interactive Dashboards
```

---

# ⚙️ Project Workflow

## 1️⃣ Reporting Semantic Layer

A dedicated reporting layer was built inside **Microsoft SQL Server** using **SQL Views**.

Instead of modifying the original Contoso tables, all business transformations were applied through SQL Views to:

- Preserve the original source data
- Improve maintainability
- Centralize business logic
- Build a clean reporting layer

One of the major transformations involved shifting the reporting timeline from **2007** to **2025**, allowing the reports to represent a modern business scenario without altering the source dataset.

---

## 2️⃣ Python Automation

The reporting views were automatically exported into optimized **Parquet** files using Python.

The export pipeline was developed in **Visual Studio Code** and optimized using multiprocessing to improve execution time.

### Python Libraries

- pandas
- PyArrow
- SQLAlchemy
- pyODBC
- concurrent.futures (ProcessPoolExecutor)
- pathlib
- warnings

---

## 3️⃣ Power BI Data Modeling

The final semantic model was built using a **Galaxy Schema (Fact Constellation)**, connecting multiple fact tables with shared conformed dimensions.

### Fact Tables

- Online Sales
- Store Sales
- Inventory
- Marketing Spend
- Customer Acquisition
- Customer Survey
- Exchange Rate
- Sales Quota
- Returns
- Order Fulfillment
- Order Payment

### Dimension Tables

- Date
- Product
- Customer
- Store
- Employee
- Promotion
- Currency
- Channel
- Payment Method
- Return Reason
- Acquisition Channel

The model was organized into multiple **Model View Layouts**, making each business domain easier to navigate while maintaining a unified enterprise semantic model.

---

# 🛠️ Technology Stack

| Category | Technologies |
|----------|--------------|
| Database | Microsoft SQL Server |
| SQL Development | SQL Server Management Studio (SSMS) |
| Programming | Python |
| IDE | Visual Studio Code |
| Data Processing | pandas, PyArrow |
| Database Connectivity | SQLAlchemy, pyODBC |
| File Format | Parquet |
| BI Platform | Power BI |
| Modeling | Galaxy Schema (Fact Constellation) |
| Analytics | DAX |

---

# 📂 Repository Structure

```
Retail-Analytics/
│
├── SQL/
│   ├── Database Layer
│   ├── SQL Views
│   └── Schema Scripts
│
├── Python/
│   ├── Export Scripts
│   └── Parquet Generator
│
├── Power BI/
│   ├── Semantic Model
│   ├── Reports
│   └── Measures
│
└── Documentation/
```

---

# 🚀 Future Work

- Composite Model Architecture
- Advanced DAX Measures
- KPI Development
- Executive Dashboard
- Performance Optimization
- Row-Level Security (RLS)

---

## 🌟 About Me

Hi! I'm **Shimaa Ezzat Tohamy**, a **Data Analyst** and **Data Analytics Instructor** with a strong passion for Business Intelligence, Data Engineering, and Analytics Solutions.

I specialize in **Power BI, SQL Server, Python, DAX, Data Modeling, ETL, and Dashboard Development**, with a focus on designing scalable reporting solutions and transforming complex datasets into actionable business insights.

I enjoy building end-to-end analytics projects—from data preparation and semantic modeling to interactive dashboards—and I'm continuously exploring modern data engineering and cloud technologies.
---

⭐ If you found this project useful, consider giving it a star.
