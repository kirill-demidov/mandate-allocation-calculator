import streamlit as st
import pandas as pd
import numpy as np
import json
import os

def get_default_data():
    return {
        "settings": {
            "total_voters": 1000000,
            "total_mandates": 100,
            "threshold": 5.0
        },
        "parties": {}
    }

def load_data(file_path='parties.json'):
    try:
        if not os.path.exists(file_path):
            return get_default_data()
            
        with open(file_path, 'r', encoding='utf-8') as f:
            data = json.load(f)
            
        # Проверяем структуру данных
        if not isinstance(data, dict):
            return get_default_data()
            
        # Проверяем наличие необходимых ключей
        if "settings" not in data:
            data["settings"] = get_default_data()["settings"]
        if "parties" not in data:
            data["parties"] = {}
            
        # Проверяем наличие всех необходимых настроек
        default_settings = get_default_data()["settings"]
        for key in default_settings:
            if key not in data["settings"]:
                data["settings"][key] = default_settings[key]
            # Преобразуем значения в правильные типы
            if key == "threshold":
                data["settings"][key] = float(data["settings"][key])
            else:
                data["settings"][key] = int(data["settings"][key])
                
        return data
    except Exception as e:
        st.error(f"Ошибка при загрузке данных: {str(e)}")
        return get_default_data()

def save_data(data, file_path='parties.json'):
    try:
        with open(file_path, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    except Exception as e:
        st.error(f"Ошибка при сохранении данных: {str(e)}")

def calculate_quota_hare(total_votes, total_mandates):
    return total_votes / total_mandates

def calculate_quota_droop(total_votes, total_mandates):
    return total_votes / (total_mandates + 1) + 1

def method_saint_lague(votes, total_mandates, k=2, d=1):
    """
    Метод Сент-Лагю (и его вариации)
    k=2, d=1 - метод Сент-Лагю
    k=1, d=1 - метод Д'Ондта
    k=1, d=2 - метод Империали
    """
    mandates = np.zeros(len(votes))
    while sum(mandates) < total_mandates:
        quotients = votes / (k * mandates + d)
        party_idx = np.argmax(quotients)
        mandates[party_idx] += 1
    return mandates

def allocate_largest_remainders(votes, quota, total_mandates):
    mandates = np.floor(votes / quota)
    remainders = votes / quota - mandates
    mandates = mandates.astype(int)
    allocated = int(np.sum(mandates))
    left = int(total_mandates - allocated)
    if left > 0:
        idx = np.argsort(-remainders)
        n = len(idx)
        for i in range(left):
            mandates[idx[i % n]] += 1
    return mandates

def calculate_mandates(votes, total_mandates, threshold=0):
    valid_votes = votes.copy()
    valid_votes[votes < threshold] = 0
    total_valid_votes = sum(valid_votes)
    quota_hare = calculate_quota_hare(total_valid_votes, total_mandates)
    quota_droop = calculate_quota_droop(total_valid_votes, total_mandates)
    # Хэйр и Друпа с наибольшими остатками
    mandates_hare = allocate_largest_remainders(valid_votes, quota_hare, total_mandates)
    mandates_droop = allocate_largest_remainders(valid_votes, quota_droop, total_mandates)
    mandates_sl = method_saint_lague(valid_votes, total_mandates, k=2, d=1)
    mandates_dhondt = method_saint_lague(valid_votes, total_mandates, k=1, d=1)
    mandates_imperiali = method_saint_lague(valid_votes, total_mandates, k=1, d=2)
    return {
        'Хэйр': mandates_hare,
        'Друпа': mandates_droop,
        'Сент-Лагю': mandates_sl,
        "Д'Ондта": mandates_dhondt,
        'Империали': mandates_imperiali
    }

def main():
    st.set_page_config(page_title="Расчет мандатов", layout="wide")
    # Переключатель языка
    lang = st.sidebar.selectbox("Язык / Language", ["Русский", "English"])
    is_ru = lang == "Русский"
    # Тексты
    txt = {
        'title': "Расчет распределения мандатов" if is_ru else "Mandate Allocation Calculator",
        'settings': "Настройки" if is_ru else "Settings",
        'voters': "Общее количество избирателей" if is_ru else "Total number of voters",
        'mandates': "Количество мандатов" if is_ru else "Number of mandates",
        'threshold': "Электоральный барьер (%)" if is_ru else "Electoral threshold (%)",
        'parties_header': "Управление партиями" if is_ru else "Party Management",
        'sum_percent': "Сумма процентов" if is_ru else "Total percent",
        'party_name': "Название партии" if is_ru else "Party name",
        'party_votes': "Процент голосов" if is_ru else "Vote percent",
        'add_party': "Добавить партию" if is_ru else "Add party",
        'delete': "Удалить" if is_ru else "Delete",
        'table_party': "Партия" if is_ru else "Party",
        'table_votes': "Голоса (%)" if is_ru else "Votes (%)",
        'export': "Экспорт в Excel" if is_ru else "Export to Excel",
        'info_add': "Добавьте партии через боковую панель" if is_ru else "Add parties using the sidebar",
        'error_sum': "Сумма процентов голосов всех партий не может превышать 100%! Сейчас: {val:.2f}%" if is_ru else "Total percent of all parties cannot exceed 100%! Now: {val:.2f}%"
    }
    st.title(txt['title'])
    
    # Загрузка данных
    data = load_data()
    
    # Боковая панель с настройками
    with st.sidebar:
        st.header(txt['settings'])
        total_voters = st.number_input(txt['voters'], 
                                     value=int(data["settings"]["total_voters"]),
                                     min_value=1,
                                     step=1)
        total_mandates = st.number_input(txt['mandates'], 
                                       value=int(data["settings"]["total_mandates"]),
                                       min_value=1,
                                       step=1)
        threshold = st.number_input(txt['threshold'], 
                                  value=float(data["settings"]["threshold"]),
                                  min_value=0.0,
                                  max_value=100.0,
                                  step=0.1)
        
        # Сохраняем настройки при изменении
        if (total_voters != data["settings"]["total_voters"] or
            total_mandates != data["settings"]["total_mandates"] or
            threshold != data["settings"]["threshold"]):
            data["settings"]["total_voters"] = total_voters
            data["settings"]["total_mandates"] = total_mandates
            data["settings"]["threshold"] = threshold
            save_data(data)
        
        st.header(txt['parties_header'])
        # Сумма процентов голосов
        current_votes_sum = float(np.sum(list(data["parties"].values())))
        if current_votes_sum > 100.0:
            st.markdown(f"<span style='color:red'><b>{txt['sum_percent']}: {current_votes_sum:.2f}%</b></span>", unsafe_allow_html=True)
        else:
            st.markdown(f"**{txt['sum_percent']}: {current_votes_sum:.2f}%**")
        new_party = st.text_input(txt['party_name'])
        new_votes = st.number_input(txt['party_votes'], 
                                  min_value=0.0, 
                                  max_value=100.0,
                                  step=0.1)
        
        if st.button(txt['add_party']):
            if new_party and new_party not in data["parties"]:
                data["parties"][new_party] = new_votes
                save_data(data)
                st.success((f"Партия {new_party} добавлена!" if is_ru else f"Party {new_party} added!"))
                st.rerun()
        
        for party in list(data["parties"].keys()):
            col1, col2 = st.columns([3, 1])
            with col1:
                st.write(f"{party} — {data['parties'][party]:.2f}%")
            with col2:
                if st.button(txt['delete'], key=f"del_{party}"):
                    del data["parties"][party]
                    save_data(data)
                    st.rerun()
    
    # Вкладки: расчёт и объяснения
    tabs = st.tabs([
        txt['title'],
        ("Объяснение методов распределения мандатов" if is_ru else "Method explanations")
    ])
    with tabs[0]:
        # --- основной функционал (как было) ---
        if data["parties"]:
            parties = list(data["parties"].keys())
            votes = np.array(list(data["parties"].values()))
            total_votes_percent = np.sum(votes)
            if total_votes_percent > 100.0:
                st.error(txt['error_sum'].format(val=total_votes_percent))
            else:
                mandates_dict = calculate_mandates(votes, total_mandates, threshold)
                table_columns = {
                    'Партия': txt['table_party'],
                    'Голоса (%)': txt['table_votes'],
                    'Хэйр': 'Hare',
                    'Друпа': 'Droop',
                    'Сент-Лагю': 'Sainte-Laguë',
                    "Д'Ондта": "D'Hondt",
                    'Империали': 'Imperiali'
                } if not is_ru else None
                results_df = pd.DataFrame({
                    'Партия': parties,
                    'Голоса (%)': votes,
                    **{method: mandates for method, mandates in mandates_dict.items()}
                })
                if table_columns:
                    results_df = results_df.rename(columns=table_columns)
                st.dataframe(results_df, use_container_width=True)
                total_row = {col: results_df[col].sum() if results_df[col].dtype != 'O' else 'Итого' if is_ru else 'Total' for col in results_df.columns}
                total_df = pd.DataFrame([total_row])
                st.dataframe(total_df, use_container_width=True)
                # График распределения голосов
                st.subheader("Распределение голосов" if is_ru else "Vote distribution")
                votes_chart = results_df.set_index(txt['table_party'])[[txt['table_votes']]]
                st.bar_chart(votes_chart)

                # График распределения мандатов (по X — системы)
                mandate_cols = [col for col in results_df.columns if col not in [txt['table_party'], txt['table_votes']]]
                mandates_chart = results_df.set_index(txt['table_party'])[mandate_cols].T
                st.bar_chart(mandates_chart)

                if st.button(txt['export']):
                    results_df.to_excel("results.xlsx" if not is_ru else "результаты.xlsx", index=False)
                    st.success(("File saved as 'results.xlsx'" if not is_ru else "Файл сохранен как 'результаты.xlsx'"))
        else:
            st.info(txt['info_add'])
    with tabs[1]:
        if is_ru:
            st.header("Объяснение методов распределения мандатов")
            st.subheader("Метод Хэйра (Hare quota)")
            st.markdown("Квота Хэйра:")
            st.latex(r"\text{Квота} = \frac{\text{Общее число голосов}}{\text{Число мандатов}}")
            st.markdown("Каждая партия получает целое число мандатов:")
            st.latex(r"\left\lfloor \frac{\text{Голоса партии}}{\text{Квота}} \right\rfloor")
            st.markdown("Оставшиеся мандаты распределяются по наибольшим остаткам.")
            st.markdown("""
**Политологический комментарий:**
Метод Хэйра обеспечивает достаточно пропорциональное представительство, но может приводить к тому, что крупные партии получают чуть меньше мандатов, а мелкие — чуть больше. Используется в некоторых странах для выборов в парламенты и местные органы власти.
""")

            st.subheader("Метод Друпа (Droop quota)")
            st.markdown("Квота Друпа:")
            st.latex(r"\text{Квота} = \frac{\text{Общее число голосов}}{\text{Число мандатов} + 1} + 1")
            st.markdown("Распределение аналогично методу Хэйра.")
            st.markdown("""
**Политологический комментарий:**
Метод Друпа чаще всего применяется в системах единого передаваемого голоса (STV) и считается более благоприятным для крупных партий, чем Хэйр. Позволяет избежать избрания слишком большого числа мелких партий.
""")

            st.subheader("Метод Сент-Лагю (Sainte-Laguë)")
            st.markdown("Мандаты распределяются по делителям: 1, 3, 5, 7, ...")
            st.markdown("На каждом шаге партия с наибольшим результатом получает мандат.")
            st.markdown("""
**Политологический комментарий:**
Метод Сент-Лагю считается более нейтральным между крупными и малыми партиями, чем Д'Ондта. Часто используется в скандинавских странах. Способствует более точному пропорциональному представительству.
""")

            st.subheader("Метод Д'Ондта (D'Hondt)")
            st.markdown("Мандаты распределяются по делителям: 1, 2, 3, 4, ...")
            st.markdown("На каждом шаге партия с наибольшим результатом получает мандат.")
            st.markdown("""
**Политологический комментарий:**
Метод Д'Ондта широко применяется в Европе (например, Испания, Португалия, Бельгия). Он немного благоприятствует крупным партиям, что способствует формированию устойчивых парламентских коалиций.
""")

            st.subheader("Метод Империали (Imperiali)")
            st.markdown("Мандаты распределяются по делителям: 2, 3, 4, 5, ...")
            st.markdown("На каждом шаге партия с наибольшим результатом получает мандат.")
            st.markdown("""
**Политологический комментарий:**
Метод Империали ещё сильнее, чем Д'Ондта, благоприятствует крупным партиям и может приводить к недопредставленности малых партий. Используется редко.
""")
        else:
            st.header("Explanation of Mandate Allocation Methods")
            st.subheader("Hare quota method")
            st.markdown("Hare quota:")
            st.latex(r"\text{Quota} = \frac{\text{Total votes}}{\text{Number of mandates}}")
            st.markdown("Each party receives:")
            st.latex(r"\left\lfloor \frac{\text{Party votes}}{\text{Quota}} \right\rfloor")
            st.markdown("Remaining mandates are distributed by the largest remainders.")
            st.markdown("""
**Political science note:**
The Hare method provides fairly proportional representation, but can result in large parties getting slightly fewer seats and small parties slightly more. Used in some countries for parliamentary and local elections.
""")

            st.subheader("Droop quota method")
            st.markdown("Droop quota:")
            st.latex(r"\text{Quota} = \frac{\text{Total votes}}{\text{Number of mandates} + 1} + 1")
            st.markdown("Distribution is similar to the Hare method.")
            st.markdown("""
**Political science note:**
The Droop method is most often used in Single Transferable Vote (STV) systems and is considered more favorable to large parties than Hare. It helps prevent too many small parties from being elected.
""")

            st.subheader("Sainte-Laguë method")
            st.markdown("Mandates are distributed using divisors: 1, 3, 5, 7, ...")
            st.markdown("At each step, the party with the highest result gets a mandate.")
            st.markdown("""
**Political science note:**
The Sainte-Laguë method is considered more neutral between large and small parties than D'Hondt. It is often used in Scandinavian countries and provides more accurate proportional representation.
""")

            st.subheader("D'Hondt method")
            st.markdown("Mandates are distributed using divisors: 1, 2, 3, 4, ...")
            st.markdown("At each step, the party with the highest result gets a mandate.")
            st.markdown("""
**Political science note:**
The D'Hondt method is widely used in Europe (e.g., Spain, Portugal, Belgium). It slightly favors large parties, which helps form stable parliamentary coalitions.
""")

            st.subheader("Imperiali method")
            st.markdown("Mandates are distributed using divisors: 2, 3, 4, 5, ...")
            st.markdown("At each step, the party with the highest result gets a mandate.")
            st.markdown("""
**Political science note:**
The Imperiali method favors large parties even more than D'Hondt and can lead to underrepresentation of small parties. It is rarely used.
""")

if __name__ == "__main__":
    main() 